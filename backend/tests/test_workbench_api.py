"""Real CPU upload/API/queue tests. No real model, network, or user data."""
from contextlib import ExitStack
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        from backend.app import settings, database, generation_service, serializers, analysis_service, routes, workbench_routes
        from backend import main
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.paths = dict(DATA_DIR=self.root, DB_PATH=self.root/'database.db', IMAGES_DIR=self.root/'images', OUTPUTS_DIR=self.root/'outputs', ANALYSIS_DIR=self.root/'analysis')
        for module in (settings,database,generation_service,serializers,analysis_service,routes,workbench_routes,main):
            for name,value in self.paths.items():
                if hasattr(module,name): self.stack.enter_context(patch.object(module,name,value))
        self.stack.enter_context(patch.dict(os.environ,{'CITY_PLANNER_TEST_MODE':'1','CITY_POSTPROCESS_CONFIG':''}))
        self.client = self.stack.enter_context(TestClient(main.create_app()))
        self.image = Image.new('RGB',(180,160),'white')
        d=ImageDraw.Draw(self.image);d.rectangle((25,30,135,110),fill=(74,165,107));d.rectangle((135,50,170,110),fill=(31,98,62))
        stream=io.BytesIO();self.image.save(stream,format='PNG');self.raw=stream.getvalue()
    def tearDown(self): self.stack.close()
    def upload(self,**data):
        return self.client.post('/jobs/postprocess',files={'file':('测试.png',self.raw,'image/png')},data={'make_3d':'false',**data})
    def wait(self,id):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            data=self.client.get('/jobs/'+id).json()
            if data['status'] in ('succeeded','failed'):return data
            time.sleep(.03)
        self.fail('Job exceeded deadline')
    def test_upload_report_download_edit_delete(self):
        response=self.upload(title='庭院方案');self.assertEqual(response.status_code,202,response.text)
        job=self.wait(response.json()['id']);self.assertEqual(job['status'],'succeeded',job)
        result=job['payload']['result'];rid=result['id']
        self.assertEqual(result['source'],'upload');self.assertFalse(result['html_exists']);self.assertEqual(result['title'],'庭院方案')
        report=self.client.get(f'/results/{rid}/quality').json()
        self.assertEqual(report['pipeline_version'],'2.0.0');self.assertEqual(report['mode'],'auto');self.assertEqual(report['height_source'],'unknown')
        self.assertEqual((self.paths['IMAGES_DIR']/f'{rid}_postprocess/source.png').read_bytes(),self.raw)
        for kind in ('cleaned','original','report'):
            r=self.client.get(f'/results/{rid}/download/{kind}');self.assertEqual(r.status_code,200);self.assertIn('attachment',r.headers['content-disposition'])
        self.assertEqual(self.client.get(f'/results/{rid}/download/model').status_code,404)
        self.assertEqual(self.client.patch(f'/results/{rid}',json={'title':'方案 B','notes':'待复核高度'}).json()['notes'],'待复核高度')
        self.assertEqual(self.client.delete(f'/results/{rid}').status_code,200)
        self.assertEqual(self.client.get(f'/results/{rid}').status_code,404)
        self.assertFalse((self.paths['IMAGES_DIR']/f'{rid}_postprocess').exists())
    def test_png_validation_and_slot_release(self):
        for _ in range(5):
            r=self.client.post('/jobs/postprocess',files={'file':('bad.png',b'bad','image/png')});self.assertEqual(r.status_code,422)
        stream=io.BytesIO();self.image.save(stream,format='JPEG')
        self.assertEqual(self.client.post('/jobs/postprocess',files={'file':('fake.png',stream.getvalue(),'image/png')}).status_code,415)
        self.assertEqual(self.upload(preset='unknown').status_code,422)
        stream=io.BytesIO();Image.new('RGB',(2100,2100)).save(stream,format='PNG')
        self.assertEqual(self.client.post('/jobs/postprocess',files={'file':('big.png',stream.getvalue(),'image/png')}).status_code,413)
        self.assertEqual(self.upload().status_code,202)
    def test_queue_bound_and_responsive_health(self):
        manager=self.client.app.state.jobs;release=threading.Event()
        def blocking(update):release.wait(5);return {'done':True}
        try:
            for _ in range(4):manager.reserve();manager.submit_reserved('test',blocking)
            self.assertEqual(self.upload().status_code,429)
            started=time.monotonic();self.assertEqual(self.client.get('/health').status_code,200);self.assertLess(time.monotonic()-started,1)
        finally:release.set()
    def test_unconfigured_generation_is_truthful(self):
        with patch.dict(os.environ,{'CITY_PLANNER_TEST_MODE':'0','SDXL_BASE_MODEL_PATH':''}):
            self.assertFalse(self.client.get('/health').json()['generation']['configured'])
            self.assertEqual(self.client.post('/jobs/generate',json={'message':'生成住宅区'}).status_code,503)
        self.assertEqual(self.client.get('/jobs/not-found').status_code,404)
    def test_color_only_preserves_foreground(self):
        job=self.wait(self.upload(preset='color_only').json()['id']);self.assertEqual(job['status'],'succeeded')
        report=self.client.get(f"/results/{job['payload']['result']['id']}/quality").json()
        self.assertFalse(report['config']['repair_geometry']);self.assertEqual(report['counts']['geometry_changed_px'],0)
    def test_png_3d_and_async_generation(self):
        job=self.wait(self.upload(make_3d='true').json()['id']);self.assertEqual(job['status'],'succeeded',job)
        result=job['payload']['result'];self.assertTrue(result['html_exists']);self.assertEqual(self.client.get(result['html_url']).status_code,200)
        response=self.client.post('/jobs/generate',json={'message':'生成住宅区规划图'});self.assertEqual(response.status_code,202)
        generated=self.wait(response.json()['id']);self.assertEqual(generated['status'],'succeeded',generated)
        self.assertEqual(generated['payload']['result']['source'],'generated')
    def test_latest_four_pngs_match_validated_v2_pixels(self):
        import numpy as np
        folder=Path(__file__).resolve().parents[1]
        samples=sorted((folder/'test_images_v2').glob('*.png'))
        self.assertEqual(len(samples),4)
        for source in samples:
            with self.subTest(source=source.name):
                response=self.client.post('/jobs/postprocess',files={'file':(source.name,source.read_bytes(),'image/png')},data={'make_3d':'false'})
                self.assertEqual(response.status_code,202,response.text)
                job=self.wait(response.json()['id']);self.assertEqual(job['status'],'succeeded',job)
                output=self.client.get(job['payload']['result']['image_url']).content
                baseline=folder/'validation_v2'/source.name/'cleaned.png'
                self.assertTrue(baseline.is_file())
                with Image.open(io.BytesIO(output)) as actual,Image.open(baseline) as expected:
                    np.testing.assert_array_equal(np.array(actual),np.array(expected))

    def test_restart_records_interrupted_state(self):
        from backend.app.database import get_connection
        from backend.app.jobs import JobManager
        with get_connection() as db:
            db.execute("INSERT INTO workbench_jobs(id,kind,status,stage) VALUES ('interrupted','test','running','working')");db.commit()
        manager=JobManager()
        try:
            restored=manager.get('interrupted');self.assertEqual(restored['status'],'failed');self.assertIn('重新启动',restored['error'])
        finally:manager.close()

if __name__=='__main__':unittest.main()

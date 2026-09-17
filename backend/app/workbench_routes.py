from __future__ import annotations
import io
import json
import logging
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .capabilities import capabilities
from .generation_service import _run_subprocess
from .repository import fetch_result, insert_result
from .routes import chat
from .schemas import ChatRequest
from .settings import DATA_DIR, IMAGES_DIR, OUTPUTS_DIR, SCRIPTS_DIR
from ..postprocessing import load_config, process_file

workbench_router = APIRouter()
log = logging.getLogger(__name__)
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 4_194_304


def _validate_png(data: bytes):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'PNG':
                raise HTTPException(415, '请上传 PNG 格式的规划图')
            if image.width * image.height > MAX_PIXELS or min(image.size) < 16:
                raise HTTPException(413, '图片需至少 16×16 像素，且总像素不超过 419 万')
            if getattr(image, 'n_frames', 1) != 1:
                raise HTTPException(415, '请使用静态 PNG 图片')
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, '图片损坏或无法读取，请重新导出 PNG') from exc


def _process_upload(source, title, preset, make_3d, update):
    result_id = str(uuid.uuid4())
    image_path = IMAGES_DIR / f'{result_id}.png'
    html_path = OUTPUTS_DIR / f'{result_id}.html'
    bundle = IMAGES_DIR / f'{result_id}_postprocess'
    committed = False
    try:
        update('修复轮廓与颜色')
        overrides = {'max_pixels': MAX_PIXELS}
        if preset == 'conservative':
            overrides.update(geometry_mode='local', remove_fragments=False)
        elif preset == 'color_only':
            overrides.update(repair_geometry=False, geometry_mode='off', remove_fragments=False)
        output = process_file(source, bundle, load_config(None, **overrides))
        shutil.copyfile(output['cleaned_path'], image_path)
        warning = None
        if make_3d:
            update('构建三维示意')
            try:
                _run_subprocess('2D23D.py', [sys.executable, str(SCRIPTS_DIR / '2D23D.py'), str(image_path), str(html_path), 'auto'])
            except Exception:
                log.exception('3D conversion failed for %s', result_id)
                warning = '图像后处理已完成，三维示意构建失败；二维结果仍可使用。'
                html_path.unlink(missing_ok=True)
        update('保存方案与质量报告')
        payload = dict(title=title, prompt='用户导入规划图', negative_prompt='', intent='postprocess',
                       area_type='unclassified', area_flag=0, model_key='image_upload', global_palette={},
                       render_preset={'source': 'upload', 'postprocess_preset': preset})
        insert_result(result_id=result_id, prompt='用户导入规划图', routed_payload=payload,
                      image_path=str(image_path), html_path=str(html_path) if html_path.is_file() else '', selection_range=None)
        committed = True
        return {'result': fetch_result(result_id), 'warning': warning}
    finally:
        source.unlink(missing_ok=True)
        if not committed:
            image_path.unlink(missing_ok=True)
            html_path.unlink(missing_ok=True)
            shutil.rmtree(bundle, ignore_errors=True)


@workbench_router.post('/jobs/postprocess', status_code=202)
async def upload_postprocess(request: Request, file: UploadFile = File(...),
                             title: str = Form('', max_length=120),
                             preset: Literal['balanced', 'conservative', 'color_only'] = Form('balanced'),
                             make_3d: bool = Form(True)):
    manager = request.app.state.jobs
    manager.reserve()
    source = None
    handed_off = False
    try:
        chunks, size = [], 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, '图片文件不能超过 12 MB')
            chunks.append(chunk)
        data = b''.join(chunks)
        await run_in_threadpool(_validate_png, data)
        incoming = DATA_DIR / 'incoming'
        incoming.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=incoming, suffix='.png', delete=False) as target:
            source = Path(target.name)
            target.write(data)
        filename = (file.filename or '导入方案').replace('\\', '/').split('/')[-1]
        label = title.strip() or Path(filename).stem[:120] or '导入方案'
        handed_off = True  # submit_reserved owns the reservation from here.
        return manager.submit_reserved('postprocess', lambda update: _process_upload(source, label, preset, make_3d, update))
    except Exception:
        if source is not None:
            source.unlink(missing_ok=True)
        if not handed_off:
            manager.slots.release()
        raise
    finally:
        await file.close()


@workbench_router.post('/jobs/generate', status_code=202)
def generate_job(request: Request, payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(400, '请输入规划目标')
    if len(payload.message) > 6000:
        raise HTTPException(422, '规划目标请控制在 6000 字以内')
    if not capabilities()['generation']['configured']:
        raise HTTPException(503, '生成模型尚未配置。你可以先使用图像后处理导入已有 PNG。')
    manager = request.app.state.jobs
    manager.reserve()
    def work(update):
        update('解析意图、生成与后处理')
        return chat(payload)
    return manager.submit_reserved('generation', work)


@workbench_router.get('/jobs/{job_id}')
def get_job(request: Request, job_id: str):
    return request.app.state.jobs.get(job_id)


@workbench_router.get('/results/{result_id}/quality')
def quality_report(result_id: str):
    result = fetch_result(result_id)
    report = IMAGES_DIR / f"{Path(result['image_url']).stem}_postprocess" / 'report.json'
    if not report.is_file():
        raise HTTPException(404, '此方案尚无后处理报告')
    return json.loads(report.read_text(encoding='utf-8'))


@workbench_router.get('/results/{result_id}/download/{kind}')
def download_result(result_id: str, kind: Literal['cleaned', 'original', 'report', 'model']):
    result = fetch_result(result_id)
    stem = Path(result['image_url'] or '').stem
    bundle = IMAGES_DIR / f'{stem}_postprocess'
    files = {'cleaned': IMAGES_DIR / f'{stem}.png', 'original': bundle / 'original.png',
             'report': bundle / 'report.json', 'model': OUTPUTS_DIR / Path(result['html_url'] or '_missing').name}
    path = files[kind]
    if not path.is_file():
        raise HTTPException(404, '该文件尚未生成')
    return FileResponse(path, filename=f'{kind}_{result_id}{path.suffix}')

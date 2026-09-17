"""Bounded single-worker jobs. SQLite status survives page refresh and process restart.
Run one Uvicorn worker; use an external queue before horizontal deployment.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from threading import BoundedSemaphore
from uuid import uuid4
from fastapi import HTTPException
from .database import get_connection

log = logging.getLogger(__name__)


class JobManager:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='planner-job')
        self.slots = BoundedSemaphore(4)
        with get_connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS workbench_jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                stage TEXT NOT NULL, payload TEXT, error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
            db.execute("UPDATE workbench_jobs SET status='failed', stage='任务中断', error='服务曾重新启动，请重新提交任务', updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')")
            db.commit()

    def reserve(self):
        if not self.slots.acquire(blocking=False):
            raise HTTPException(429, '队列已满，请待当前任务完成后重试', headers={'Retry-After': '5'})

    def submit_reserved(self, kind, work):
        job_id = str(uuid4())
        try:
            with get_connection() as db:
                db.execute("INSERT INTO workbench_jobs (id,kind,status,stage) VALUES (?,?,'queued','等待处理')", (job_id, kind))
                db.commit()
            self.pool.submit(self._run, job_id, work)
        except Exception:
            self.slots.release()
            raise
        return self.get(job_id)

    def _set(self, job_id, status, stage, payload=None, error=None):
        with get_connection() as db:
            db.execute('UPDATE workbench_jobs SET status=?,stage=?,payload=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                       (status, stage, json.dumps(payload, ensure_ascii=False) if payload else None, error, job_id))
            db.commit()

    def _run(self, job_id, work):
        try:
            self._set(job_id, 'running', '开始处理')
            result = work(lambda stage: self._set(job_id, 'running', stage))
            self._set(job_id, 'succeeded', '处理完成', result)
        except Exception as exc:
            log.exception('Job %s failed', job_id)
            message = exc.detail if isinstance(exc, HTTPException) and exc.status_code < 500 else '任务未完成，请检查服务配置后重试。原始图片不会被覆盖。'
            self._set(job_id, 'failed', '处理失败', error=str(message))
        finally:
            self.slots.release()

    def get(self, job_id):
        with get_connection() as db:
            row = db.execute('SELECT * FROM workbench_jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '任务不存在')
        data = dict(row)
        data['payload'] = json.loads(data['payload']) if data['payload'] else None
        return data

    def close(self):
        self.pool.shutdown(wait=True)

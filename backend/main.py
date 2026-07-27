from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.database import init_db
from backend.app.routes import router
from backend.app.settings import ANALYSIS_DIR, IMAGES_DIR, OUTPUTS_DIR


def create_app() -> FastAPI:
    """装配 API，并在挂载静态目录前完成数据库与运行目录初始化。"""
    init_db()

    app = FastAPI(title="Urban Planner Assistant API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    # 生成图片、3D HTML 和分析热力图通过独立静态路由返回给前端。
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
    app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")
    app.mount("/analysis", StaticFiles(directory=ANALYSIS_DIR), name="analysis")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(PROJECT_DIR / ".env")

DATA_DIR = Path(os.getenv("CITY_PLANNER_DATA_DIR", str(BACKEND_DIR))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "database.db"
IMAGES_DIR = DATA_DIR / "images"
OUTPUTS_DIR = DATA_DIR / "outputs"
ANALYSIS_DIR = DATA_DIR / "analysis"
SCRIPTS_DIR = BACKEND_DIR / "scripts"

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip().strip('"')
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
).strip()
DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen3.7-plus").strip()


def is_test_mode() -> bool:
    return os.getenv("CITY_PLANNER_TEST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

from __future__ import annotations

import sqlite3

from .settings import ANALYSIS_DIR, DB_PATH, IMAGES_DIR, OUTPUTS_DIR


RESULT_COLUMNS = {
    "title": "TEXT",
    "rewritten_prompt": "TEXT",
    "negative_prompt": "TEXT",
    "area_type": "TEXT",
    "area_flag": "INTEGER",
    "model_key": "TEXT",
    "color_palette": "TEXT",
    "render_preset": "TEXT",
    "selection_range": "TEXT",
    "notes": "TEXT DEFAULT ''",
    "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
}


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                id TEXT PRIMARY KEY,
                title TEXT,
                prompt TEXT,
                rewritten_prompt TEXT,
                negative_prompt TEXT,
                image_path TEXT,
                html_path TEXT,
                intent TEXT,
                area_type TEXT,
                area_flag INTEGER,
                model_key TEXT,
                color_palette TEXT,
                render_preset TEXT,
                selection_range TEXT,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        existing_columns = {
            row["name"] for row in cursor.execute("PRAGMA table_info(results)").fetchall()
        }
        for column_name, definition in RESULT_COLUMNS.items():
            if column_name not in existing_columns:
                cursor.execute(f"ALTER TABLE results ADD COLUMN {column_name} {definition}")

        connection.commit()

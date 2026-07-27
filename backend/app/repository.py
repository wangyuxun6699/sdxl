from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from .database import get_connection
from .serializers import serialize_result


def fetch_result_row(result_id: str) -> sqlite3.Row:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM results WHERE id = ?",
            (result_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="结果不存在")
    return row


def fetch_result(result_id: str) -> dict[str, Any]:
    return serialize_result(fetch_result_row(result_id))


def list_results() -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM results ORDER BY datetime(created_at) DESC, id DESC"
        ).fetchall()
    return [serialize_result(row) for row in rows]


def insert_result(
    *,
    result_id: str,
    prompt: str,
    routed_payload: dict[str, Any],
    image_path: str,
    html_path: str,
    selection_range: dict[str, Any] | None,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO results (
                id, title, prompt, rewritten_prompt, negative_prompt, image_path, html_path,
                intent, area_type, area_flag, model_key, color_palette, render_preset, selection_range
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                routed_payload["title"],
                prompt,
                routed_payload["prompt"],
                routed_payload["negative_prompt"],
                image_path,
                html_path,
                routed_payload["intent"],
                routed_payload["area_type"],
                routed_payload["area_flag"],
                routed_payload["model_key"],
                json.dumps(routed_payload["global_palette"], ensure_ascii=False),
                json.dumps(routed_payload["render_preset"], ensure_ascii=False),
                json.dumps(selection_range, ensure_ascii=False) if selection_range else None,
            ),
        )
        connection.commit()


def update_result(result_id: str, *, title: str | None, notes: str | None) -> dict[str, Any]:
    updates: list[str] = []
    values: list[Any] = []

    if title is not None:
        updates.append("title = ?")
        values.append(title.strip())
    if notes is not None:
        updates.append("notes = ?")
        values.append(notes.strip())

    if not updates:
        return fetch_result(result_id)

    values.append(result_id)
    with get_connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE results
            SET {", ".join(updates)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values,
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="结果不存在")
    return fetch_result(result_id)


def delete_result_record(result_id: str) -> None:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM results WHERE id = ?", (result_id,))
        connection.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="结果不存在")

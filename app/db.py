"""Small SQLite store for exact page snapshots and user-entered events."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings


def connect() -> sqlite3.Connection:
    path = get_settings().database_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                site_key TEXT NOT NULL,
                url TEXT NOT NULL,
                keyword TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                page_snapshot TEXT NOT NULL,
                findings_json TEXT NOT NULL,
                recommendation_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analyses_site_time
                ON analyses(site_key, created_at DESC);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                analysis_id TEXT,
                site_key TEXT NOT NULL,
                url TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(analysis_id) REFERENCES analyses(id)
            );
            """
        )


def save_analysis(record: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO analyses
               (id, site_key, url, keyword, created_at, page_snapshot,
                findings_json, recommendation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["id"], record["site_key"], record["url"],
                record["keyword"], record["created_at"],
                json.dumps(record["page_snapshot"]),
                json.dumps(record["findings"]),
                json.dumps(record["recommendation"]),
            ),
        )


def latest_analysis(site_key: str, url: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE site_key=? AND url=? ORDER BY created_at DESC LIMIT 1",
            (site_key, url),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["page_snapshot"] = json.loads(result["page_snapshot"])
    result["findings"] = json.loads(result.pop("findings_json"))
    result["recommendation"] = json.loads(result.pop("recommendation_json"))
    return result


def list_history(site_key: str, limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, url, keyword, created_at, findings_json, recommendation_json "
            "FROM analyses WHERE site_key=? ORDER BY created_at DESC LIMIT ?",
            (site_key, limit),
        ).fetchall()
    return [
        {
            "id": row["id"], "url": row["url"], "keyword": row["keyword"],
            "created_at": row["created_at"],
            "findings": json.loads(row["findings_json"]),
            "recommendation": json.loads(row["recommendation_json"]),
        }
        for row in rows
    ]


def save_event(record: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (id, analysis_id, site_key, url, kind, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record["id"], record.get("analysis_id"), record["site_key"],
                record["url"], record["kind"], record["content"],
                record.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ),
        )


def list_events(site_key: str, limit: int = 30) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE site_key=? ORDER BY created_at DESC LIMIT ?",
            (site_key, limit),
        ).fetchall()
    return [dict(row) for row in rows]

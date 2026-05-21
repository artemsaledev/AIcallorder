from __future__ import annotations

import sqlite3
import json
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Tuple

from loom_automation.models import MeetingArtifacts, MeetingMetadata


class SQLiteStorage:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite URLs are supported in the local scaffold.")
        db_path = database_url.replace("sqlite:///", "", 1)
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    loom_video_id TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    meeting_type TEXT NOT NULL,
                    recorded_at TEXT,
                    participants_json TEXT NOT NULL,
                    transcript_text TEXT NOT NULL,
                    artifacts_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_type TEXT NOT NULL,
                    initiated_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_publications (
                    loom_video_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    google_status TEXT NOT NULL,
                    telegram_status TEXT NOT NULL,
                    register_status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    google_result_json TEXT,
                    telegram_result_json TEXT,
                    register_result_json TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (loom_video_id) REFERENCES meetings(loom_video_id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()

    def upsert_meeting(self, meeting: MeetingMetadata, transcript_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meetings (
                    loom_video_id, source_url, title, meeting_type, recorded_at, participants_json, transcript_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(loom_video_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    title = excluded.title,
                    meeting_type = excluded.meeting_type,
                    recorded_at = excluded.recorded_at,
                    participants_json = excluded.participants_json,
                    transcript_text = excluded.transcript_text
                """,
                (
                    meeting.loom_video_id,
                    meeting.source_url,
                    meeting.title,
                    meeting.meeting_type,
                    meeting.recorded_at.isoformat() if meeting.recorded_at else None,
                    str(meeting.participants),
                    transcript_text,
                ),
            )
            conn.commit()

    def save_artifacts(self, loom_video_id: str, artifacts: MeetingArtifacts) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE meetings SET artifacts_json = ? WHERE loom_video_id = ?",
                (artifacts.model_dump_json(), loom_video_id),
            )
            conn.commit()

    def has_meeting(self, loom_video_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM meetings WHERE loom_video_id = ? LIMIT 1",
                (loom_video_id,),
            ).fetchone()
        return row is not None

    def has_source_url(self, source_url: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM meetings WHERE source_url = ? LIMIT 1",
                (source_url,),
            ).fetchone()
        return row is not None

    def list_artifacts_for_day(self, report_date: str) -> List[Tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title, artifacts_json
                FROM meetings
                WHERE recorded_at LIKE ?
                  AND artifacts_json IS NOT NULL
                ORDER BY recorded_at ASC
                """,
                (f"{report_date}%",),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def list_meeting_records_for_day(self, report_date: str) -> List[Tuple[str, str, str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT loom_video_id, title, source_url, artifacts_json
                FROM meetings
                WHERE recorded_at LIKE ?
                  AND artifacts_json IS NOT NULL
                ORDER BY recorded_at ASC
                """,
                (f"{report_date}%",),
            ).fetchall()
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    def list_recent_meetings(self, limit: int = 25, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    meetings.loom_video_id,
                    source_url,
                    title,
                    meeting_type,
                    recorded_at,
                    transcript_text,
                    artifacts_json,
                    meeting_publications.status,
                    meeting_publications.google_status,
                    meeting_publications.telegram_status,
                    meeting_publications.register_status,
                    meeting_publications.attempts,
                    meeting_publications.last_error,
                    meeting_publications.updated_at
                FROM meetings
                LEFT JOIN meeting_publications
                    ON meeting_publications.loom_video_id = meetings.loom_video_id
                ORDER BY COALESCE(recorded_at, '') DESC, meetings.rowid DESC
                LIMIT ?
                OFFSET ?
                """,
                (max(1, limit), max(0, offset)),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            artifacts = None
            if row[6]:
                try:
                    artifacts = json.loads(row[6])
                except json.JSONDecodeError:
                    artifacts = None
            results.append(
                {
                    "loom_video_id": row[0],
                    "source_url": row[1],
                    "title": row[2],
                    "meeting_type": row[3],
                    "recorded_at": row[4],
                    "transcript_text": row[5],
                    "artifacts": artifacts,
                    "publication": {
                        "status": row[7],
                        "google_status": row[8],
                        "telegram_status": row[9],
                        "register_status": row[10],
                        "attempts": row[11],
                        "last_error": row[12],
                        "updated_at": row[13],
                    }
                    if row[7]
                    else None,
                }
            )
        return results

    def count_meetings(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM meetings").fetchone()
        return int(row[0]) if row else 0

    def get_meeting(self, loom_video_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT loom_video_id, source_url, title, meeting_type, recorded_at, transcript_text, artifacts_json
                FROM meetings
                WHERE loom_video_id = ?
                LIMIT 1
                """,
                (loom_video_id,),
            ).fetchone()
        if not row:
            return None
        artifacts = None
        if row[6]:
            try:
                artifacts = json.loads(row[6])
            except json.JSONDecodeError:
                artifacts = None
        return {
            "loom_video_id": row[0],
            "source_url": row[1],
            "title": row[2],
            "meeting_type": row[3],
            "recorded_at": row[4],
            "transcript_text": row[5],
            "artifacts": artifacts,
        }

    def begin_meeting_publication(self, loom_video_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO meeting_publications (
                    loom_video_id,
                    status,
                    google_status,
                    telegram_status,
                    register_status,
                    attempts,
                    created_at,
                    updated_at
                ) VALUES (?, 'in_progress', 'pending', 'pending', 'pending', 1, ?, ?)
                ON CONFLICT(loom_video_id) DO UPDATE SET
                    status = 'in_progress',
                    attempts = meeting_publications.attempts + 1,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (loom_video_id, now, now),
            )
            conn.commit()
        return self.get_meeting_publication(loom_video_id) or {}

    def update_meeting_publication_step(
        self,
        loom_video_id: str,
        *,
        step: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        if step not in {"google", "telegram", "register"}:
            raise ValueError(f"Unsupported publication step: {step}")
        now = datetime.now(timezone.utc).isoformat()
        status_column = f"{step}_status"
        result_column = f"{step}_result_json"
        result_json = json.dumps(result or {}, ensure_ascii=False) if result is not None else None
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE meeting_publications
                SET {status_column} = ?,
                    {result_column} = COALESCE(?, {result_column}),
                    last_error = ?,
                    updated_at = ?
                WHERE loom_video_id = ?
                """,
                (status, result_json, error, now, loom_video_id),
            )
            conn.commit()
        return self.get_meeting_publication(loom_video_id) or {}

    def complete_meeting_publication(self, loom_video_id: str, *, status: str, error: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE meeting_publications
                SET status = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE loom_video_id = ?
                """,
                (status, error, now, loom_video_id),
            )
            conn.commit()

    def get_meeting_publication(self, loom_video_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    loom_video_id,
                    status,
                    google_status,
                    telegram_status,
                    register_status,
                    attempts,
                    google_result_json,
                    telegram_result_json,
                    register_result_json,
                    last_error,
                    created_at,
                    updated_at
                FROM meeting_publications
                WHERE loom_video_id = ?
                LIMIT 1
                """,
                (loom_video_id,),
            ).fetchone()
        if not row:
            return None

        def parse_json(value: str | None) -> dict[str, Any] | None:
            if not value:
                return None
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {"raw": value}
            return parsed if isinstance(parsed, dict) else {"value": parsed}

        return {
            "loom_video_id": row[0],
            "status": row[1],
            "google_status": row[2],
            "telegram_status": row[3],
            "register_status": row[4],
            "attempts": row[5],
            "google_result": parse_json(row[6]),
            "telegram_result": parse_json(row[7]),
            "register_result": parse_json(row[8]),
            "last_error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    def list_unpublished_meeting_records(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    meetings.loom_video_id,
                    source_url,
                    title,
                    meeting_type,
                    recorded_at,
                    participants_json,
                    transcript_text,
                    artifacts_json,
                    meeting_publications.status,
                    meeting_publications.attempts
                FROM meetings
                JOIN meeting_publications
                    ON meeting_publications.loom_video_id = meetings.loom_video_id
                WHERE meeting_publications.status != 'published'
                  AND meetings.artifacts_json IS NOT NULL
                ORDER BY meeting_publications.updated_at ASC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            artifacts = None
            try:
                artifacts = json.loads(row[7]) if row[7] else None
            except json.JSONDecodeError:
                artifacts = None
            participants: list[str] = []
            try:
                loaded = json.loads(row[5] or "[]")
                if isinstance(loaded, list):
                    participants = [str(item) for item in loaded]
            except json.JSONDecodeError:
                try:
                    loaded = ast.literal_eval(row[5] or "[]")
                    if isinstance(loaded, list):
                        participants = [str(item) for item in loaded]
                except (SyntaxError, ValueError):
                    participants = []
            results.append(
                {
                    "loom_video_id": row[0],
                    "source_url": row[1],
                    "title": row[2],
                    "meeting_type": row[3],
                    "recorded_at": row[4],
                    "participants": participants,
                    "transcript_text": row[6],
                    "artifacts": artifacts,
                    "publication_status": row[8],
                    "publication_attempts": row[9],
                }
            )
        return results

    def delete_meeting(self, loom_video_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM meetings WHERE loom_video_id = ?", (loom_video_id,))
            conn.commit()
        return cursor.rowcount > 0

    def clear_meetings(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM meetings")
            conn.commit()
        return cursor.rowcount

    def create_run_log(
        self,
        *,
        run_type: str,
        initiated_by: str,
        status: str,
        started_at: str,
        finished_at: str,
        summary: dict[str, Any],
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO run_logs (run_type, initiated_by, status, started_at, finished_at, summary_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_type, initiated_by, status, started_at, finished_at, json.dumps(summary, ensure_ascii=False)),
            )
            conn.commit()
        return int(cursor.lastrowid)

    def list_recent_run_logs(self, limit: int = 25, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_type, initiated_by, status, started_at, finished_at, summary_json
                FROM run_logs
                ORDER BY id DESC
                LIMIT ?
                OFFSET ?
                """,
                (max(1, limit), max(0, offset)),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            try:
                summary = json.loads(row[6])
            except json.JSONDecodeError:
                summary = {"raw": row[6]}
            results.append(
                {
                    "id": row[0],
                    "run_type": row[1],
                    "initiated_by": row[2],
                    "status": row[3],
                    "started_at": row[4],
                    "finished_at": row[5],
                    "summary": summary,
                }
            )
        return results

    def count_run_logs(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM run_logs").fetchone()
        return int(row[0]) if row else 0

    def clear_run_logs(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM run_logs")
            conn.commit()
        return cursor.rowcount

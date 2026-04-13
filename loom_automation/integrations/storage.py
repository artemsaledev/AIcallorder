from __future__ import annotations

import sqlite3
from pathlib import Path
import json
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

    def list_recent_meetings(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT loom_video_id, source_url, title, meeting_type, recorded_at, transcript_text, artifacts_json
                FROM meetings
                ORDER BY COALESCE(recorded_at, '') DESC, rowid DESC
                LIMIT ?
                """,
                (max(1, limit),),
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
                }
            )
        return results

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

    def list_recent_run_logs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_type, initiated_by, status, started_at, finished_at, summary_json
                FROM run_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, limit),),
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

    def clear_run_logs(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM run_logs")
            conn.commit()
        return cursor.rowcount

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from loom_automation.integrations.google_workspace import GoogleWorkspacePublisher
from loom_automation.integrations.meeting_digest_bot import MeetingDigestBotClient
from loom_automation.integrations.storage import SQLiteStorage
from loom_automation.integrations.telegram import TelegramNotifier
from loom_automation.models import LoomImportRequest, MeetingArtifacts, MeetingMetadata, ProcessFolderRequest, ProcessMeetingRequest
from loom_automation.modules.collector import LoomCollector
from loom_automation.modules.summarizer import Summarizer
from loom_automation.modules.telegram_reporter import TelegramReporter
from loom_automation.modules.transcript_processor import TranscriptProcessor
from loom_automation.modules.transcriber import Transcriber


logger = logging.getLogger(__name__)


@dataclass
class DiscordLoomPipeline:
    collector: LoomCollector
    transcriber: Transcriber
    transcript_processor: TranscriptProcessor
    summarizer: Summarizer
    telegram_reporter: TelegramReporter
    storage: SQLiteStorage
    google_publisher: GoogleWorkspacePublisher
    telegram_notifier: TelegramNotifier
    meeting_digest_bot: MeetingDigestBotClient | None = None

    def run(self, request: ProcessMeetingRequest) -> dict:
        collected = self._collect(request)
        meeting = self.collector.to_meeting_metadata(collected, meeting_type=request.meeting_type)
        transcript = self.transcriber.build_transcript(collected)
        raw_transcript_text = transcript.transcript_text
        processed_transcript_text = self.transcript_processor.process(
            raw_transcript_text,
            meeting_title=meeting.title,
        )
        artifacts = self.summarizer.summarize(
            processed_transcript_text,
            meeting_title=meeting.title,
            meeting_type=meeting.meeting_type,
        )
        if not artifacts.telegram_digest:
            artifacts.telegram_digest = self.telegram_reporter.render_meeting_digest(meeting, artifacts)

        self.storage.upsert_meeting(meeting, raw_transcript_text)
        self.storage.save_artifacts(meeting.loom_video_id, artifacts)

        publication_result = self._publish_saved_meeting(
            meeting=meeting,
            artifacts=artifacts,
            raw_transcript_text=raw_transcript_text,
        )

        return {
            "pipeline": "discord-loom",
            "transcript_source": transcript.source,
            "meeting": meeting.model_dump(),
            "artifacts": artifacts.model_dump(),
            **publication_result,
        }

    def run_folder(self, request: ProcessFolderRequest) -> dict:
        collected_items = self.collector.collect_from_folder(
            folder_path=request.folder_path,
            tags=["discord", request.meeting_type, "local-folder"],
        )
        known_urls = self._load_known_urls()
        results = []
        for collected in collected_items:
            if collected.source_url in known_urls:
                continue
            meeting = self.collector.to_meeting_metadata(collected, meeting_type=request.meeting_type)
            transcript = self.transcriber.build_transcript(collected)
            raw_transcript_text = transcript.transcript_text
            processed_transcript_text = self.transcript_processor.process(
                raw_transcript_text,
                meeting_title=meeting.title,
            )
            artifacts = self.summarizer.summarize(
                processed_transcript_text,
                meeting_title=meeting.title,
                meeting_type=meeting.meeting_type,
            )
            if not artifacts.telegram_digest:
                artifacts.telegram_digest = self.telegram_reporter.render_meeting_digest(meeting, artifacts)

            self.storage.upsert_meeting(meeting, raw_transcript_text)
            self.storage.save_artifacts(meeting.loom_video_id, artifacts)
            known_urls.add(collected.source_url)

            results.append(
                {
                    "meeting": meeting.model_dump(),
                    "transcript_source": transcript.source,
                    "artifacts": artifacts.model_dump(),
                }
            )

        return {
            "pipeline": "discord-loom-folder",
            "folder_path": request.folder_path,
            "processed_count": len(results),
            "results": results,
        }

    def run_loom_import(self, request: LoomImportRequest) -> dict:
        retry_results = self.retry_unpublished_meetings(limit=max(10, request.limit))
        known_ids = self._load_known_video_ids()
        known_urls = self._load_known_urls()
        collected_items = self.collector.collect_new_loom_videos(
            limit=request.limit,
            known_video_ids=known_ids,
            known_urls=known_urls,
            primary_text_query=request.primary_text_query,
            primary_date_query=request.primary_date_query,
            search_results_limit=request.search_results_limit,
            title_include_keywords=request.title_include_keywords,
            title_exclude_keywords=request.title_exclude_keywords,
            recorded_date_from=request.recorded_date_from,
            recorded_date_to=request.recorded_date_to,
        )
        collection_debug = dict(getattr(self.collector, "last_collection_debug", {}) or {})
        results = []
        for collected in collected_items:
            meeting = self.collector.to_meeting_metadata(collected, meeting_type=request.meeting_type)
            transcript = self.transcriber.build_transcript(collected)
            raw_transcript_text = transcript.transcript_text
            processed_transcript_text = self.transcript_processor.process(
                raw_transcript_text,
                meeting_title=meeting.title,
            )
            artifacts = self.summarizer.summarize(
                processed_transcript_text,
                meeting_title=meeting.title,
                meeting_type=meeting.meeting_type,
            )
            if not artifacts.telegram_digest:
                artifacts.telegram_digest = self.telegram_reporter.render_meeting_digest(meeting, artifacts)

            self.storage.upsert_meeting(meeting, raw_transcript_text)
            self.storage.save_artifacts(meeting.loom_video_id, artifacts)

            publication_result = self._publish_saved_meeting(
                meeting=meeting,
                artifacts=artifacts,
                raw_transcript_text=raw_transcript_text,
            )
            results.append(
                {
                    "meeting": meeting.model_dump(),
                    "transcript_source": transcript.source,
                    "artifacts": artifacts.model_dump(),
                    **publication_result,
                }
            )

        return {
            "pipeline": "loom-auto-import",
            "processed_count": len(results),
            "retry_count": len(retry_results),
            "collection_debug": collection_debug,
            "retry_results": retry_results,
            "results": results,
        }

    def retry_unpublished_meetings(self, limit: int = 10) -> list[dict[str, Any]]:
        retry_records = self.storage.list_unpublished_meeting_records(limit=limit)
        results: list[dict[str, Any]] = []
        for record in retry_records:
            artifacts_payload = record.get("artifacts")
            if not artifacts_payload:
                continue
            try:
                artifacts = MeetingArtifacts.model_validate(artifacts_payload)
                meeting = MeetingMetadata(
                    loom_video_id=record["loom_video_id"],
                    source_url=record["source_url"],
                    title=record["title"],
                    meeting_type=record["meeting_type"],
                    recorded_at=datetime.fromisoformat(record["recorded_at"]) if record.get("recorded_at") else None,
                    participants=record.get("participants") or [],
                )
                publication_result = self._publish_saved_meeting(
                    meeting=meeting,
                    artifacts=artifacts,
                    raw_transcript_text=record.get("transcript_text") or "",
                    retry=True,
                )
                results.append(
                    {
                        "meeting": meeting.model_dump(),
                        "retry": True,
                        **publication_result,
                    }
                )
            except Exception as exc:
                logger.exception("Failed to retry publication for Loom %s", record.get("loom_video_id"))
                self.storage.complete_meeting_publication(
                    record["loom_video_id"],
                    status="error",
                    error=f"{exc.__class__.__name__}: {exc}",
                )
                results.append(
                    {
                        "meeting": {
                            "loom_video_id": record.get("loom_video_id"),
                            "title": record.get("title"),
                        },
                        "retry": True,
                        "publication_status": "error",
                        "error": str(exc),
                    }
                )
        return results

    def _collect(self, request: ProcessMeetingRequest):
        source = request.collector_source or "loom"
        if source == "local-file":
            if not request.local_video_path:
                raise ValueError("local_video_path is required for collector_source=local-file")
            return self.collector.collect_from_local_file(
                file_path=request.local_video_path,
                title=request.title,
                tags=["discord", request.meeting_type, "local-file"],
            )

        if source == "loom":
            if not (request.loom_video_id or request.loom_url):
                raise ValueError("loom_video_id or loom_url is required for collector_source=loom")
            if not request.transcript_text:
                raise ValueError(
                    "collector_source=loom expects transcript_text from Loom. "
                    "This scenario is configured to rely on Loom's own transcript for Loom videos."
                )
            loom_video_id = request.loom_video_id or request.loom_url.rsplit("/", 1)[-1]
            source_url = request.loom_url or f"https://www.loom.com/share/{loom_video_id}"
            return self.collector.collect_from_manual_input(
                loom_video_id=loom_video_id,
                source_url=source_url,
                title=request.title,
                transcript_text=request.transcript_text,
                tags=["discord", request.meeting_type, "loom"],
            )

        raise ValueError(f"Unsupported collector_source: {source}")

    def _load_known_video_ids(self) -> set[str]:
        with self.storage._connect() as conn:
            rows = conn.execute("SELECT loom_video_id FROM meetings").fetchall()
        return {row[0] for row in rows}

    def _load_known_urls(self) -> set[str]:
        with self.storage._connect() as conn:
            rows = conn.execute("SELECT source_url FROM meetings").fetchall()
        return {row[0] for row in rows}

    def _publish_saved_meeting(
        self,
        *,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        raw_transcript_text: str,
        retry: bool = False,
    ) -> dict[str, Any]:
        self.storage.begin_meeting_publication(meeting.loom_video_id)
        publication = self.storage.get_meeting_publication(meeting.loom_video_id) or {}

        google_result = self._stored_success_result(publication, "google")
        if not google_result:
            try:
                google_result = self.google_publisher.publish_meeting_artifacts(meeting, artifacts, raw_transcript_text)
                google_error = self._google_result_error(google_result)
                if google_error:
                    self.storage.update_meeting_publication_step(
                        meeting.loom_video_id,
                        step="google",
                        status="error",
                        result=google_result,
                        error=google_error,
                    )
                    self.storage.complete_meeting_publication(meeting.loom_video_id, status="error", error=google_error)
                    return self._publication_response(
                        meeting.loom_video_id,
                        google_result=google_result,
                        telegram_result={"sent": False, "reason": "Skipped because Google publication failed."},
                        meeting_digest_bot_result={"registered": False, "reason": "Skipped because Google publication failed."},
                        retry=retry,
                    )
                self.storage.update_meeting_publication_step(
                    meeting.loom_video_id,
                    step="google",
                    status="success",
                    result=google_result,
                )
            except Exception as exc:
                error = f"{exc.__class__.__name__}: {exc}"
                self.storage.update_meeting_publication_step(
                    meeting.loom_video_id,
                    step="google",
                    status="error",
                    error=error,
                )
                self.storage.complete_meeting_publication(meeting.loom_video_id, status="error", error=error)
                logger.warning("Google publication failed for Loom %s: %s", meeting.loom_video_id, exc)
                return self._publication_response(
                    meeting.loom_video_id,
                    google_result={"error": error},
                    telegram_result={"sent": False, "reason": "Skipped because Google publication failed."},
                    meeting_digest_bot_result={"registered": False, "reason": "Skipped because Google publication failed."},
                    retry=retry,
                )

        artifacts.telegram_digest = self.telegram_reporter.append_meeting_links(
            artifacts.telegram_digest,
            meeting=meeting,
            google_doc_url=google_result.get("google_doc_url") or self.google_publisher.current_doc_url(),
            doc_section_title=self.google_publisher.section_title(meeting),
            transcript_doc_url=google_result.get("transcript_doc_url") or self.google_publisher.current_transcript_doc_url(),
            transcript_section_title=self.google_publisher.transcript_section_title(meeting),
        )

        publication = self.storage.get_meeting_publication(meeting.loom_video_id) or {}
        telegram_result = self._stored_success_result(publication, "telegram")
        if not telegram_result:
            try:
                telegram_result = self.telegram_notifier.send_digest(artifacts.telegram_digest)
                if not telegram_result.get("sent"):
                    error = str(telegram_result.get("reason") or "Telegram send returned sent=false.")
                    self.storage.update_meeting_publication_step(
                        meeting.loom_video_id,
                        step="telegram",
                        status="error",
                        result=telegram_result,
                        error=error,
                    )
                    self.storage.complete_meeting_publication(meeting.loom_video_id, status="error", error=error)
                    return self._publication_response(
                        meeting.loom_video_id,
                        google_result=google_result,
                        telegram_result=telegram_result,
                        meeting_digest_bot_result={"registered": False, "reason": "Skipped because Telegram send failed."},
                        retry=retry,
                    )
                self.storage.update_meeting_publication_step(
                    meeting.loom_video_id,
                    step="telegram",
                    status="success",
                    result=telegram_result,
                )
            except Exception as exc:
                error = f"{exc.__class__.__name__}: {exc}"
                self.storage.update_meeting_publication_step(
                    meeting.loom_video_id,
                    step="telegram",
                    status="error",
                    error=error,
                )
                self.storage.complete_meeting_publication(meeting.loom_video_id, status="error", error=error)
                logger.warning("Telegram publication failed for Loom %s: %s", meeting.loom_video_id, exc)
                return self._publication_response(
                    meeting.loom_video_id,
                    google_result=google_result,
                    telegram_result={"sent": False, "error": error},
                    meeting_digest_bot_result={"registered": False, "reason": "Skipped because Telegram send failed."},
                    retry=retry,
                )

        publication = self.storage.get_meeting_publication(meeting.loom_video_id) or {}
        meeting_digest_bot_result = self._stored_success_result(publication, "register")
        if not meeting_digest_bot_result:
            meeting_digest_bot_result = self._register_meeting_publication(
                meeting=meeting,
                telegram_result=telegram_result,
                google_result=google_result,
                artifacts=artifacts.model_dump(),
            )
            register_ok = bool(
                meeting_digest_bot_result.get("registered")
                or meeting_digest_bot_result.get("ok")
                or meeting_digest_bot_result.get("record")
            )
            if register_ok or not self.meeting_digest_bot or not self.meeting_digest_bot.enabled:
                self.storage.update_meeting_publication_step(
                    meeting.loom_video_id,
                    step="register",
                    status="success" if register_ok else "skipped",
                    result=meeting_digest_bot_result,
                )
            else:
                error = str(meeting_digest_bot_result.get("error") or meeting_digest_bot_result.get("reason") or "MeetingDigestBot registration failed.")
                self.storage.update_meeting_publication_step(
                    meeting.loom_video_id,
                    step="register",
                    status="error",
                    result=meeting_digest_bot_result,
                    error=error,
                )
                self.storage.complete_meeting_publication(meeting.loom_video_id, status="error", error=error)
                return self._publication_response(
                    meeting.loom_video_id,
                    google_result=google_result,
                    telegram_result=telegram_result,
                    meeting_digest_bot_result=meeting_digest_bot_result,
                    retry=retry,
                )

        self.storage.complete_meeting_publication(meeting.loom_video_id, status="published")
        return self._publication_response(
            meeting.loom_video_id,
            google_result=google_result,
            telegram_result=telegram_result,
            meeting_digest_bot_result=meeting_digest_bot_result,
            retry=retry,
        )

    def _publication_response(
        self,
        loom_video_id: str,
        *,
        google_result: dict[str, Any],
        telegram_result: dict[str, Any],
        meeting_digest_bot_result: dict[str, Any],
        retry: bool,
    ) -> dict[str, Any]:
        publication = self.storage.get_meeting_publication(loom_video_id) or {}
        return {
            "google": google_result,
            "telegram": telegram_result,
            "meeting_digest_bot": meeting_digest_bot_result,
            "publication": publication,
            "publication_status": publication.get("status"),
            "retry": retry,
        }

    def _stored_success_result(self, publication: dict[str, Any], step: str) -> dict[str, Any] | None:
        if publication.get(f"{step}_status") not in {"success", "skipped"}:
            return None
        result = publication.get(f"{step}_result")
        return result if isinstance(result, dict) else None

    def _google_result_error(self, google_result: dict[str, Any]) -> str | None:
        for key in ("google_doc_url", "transcript_doc_url"):
            value = google_result.get(key)
            if isinstance(value, str) and value.startswith("google-"):
                return f"{key}: {value}"
        note = google_result.get("note")
        if isinstance(note, str) and "credentials" in note.lower():
            return note
        return None

    def _register_meeting_publication(
        self,
        *,
        meeting,
        telegram_result: dict,
        google_result: dict | None,
        artifacts: dict,
    ) -> dict:
        if not self.meeting_digest_bot or not telegram_result.get("sent"):
            return {"registered": False, "reason": "MeetingDigestBot is disabled or Telegram send failed."}
        try:
            result = self.meeting_digest_bot.register_meeting_publication(
                meeting=meeting,
                telegram_result=telegram_result,
                google_result=google_result,
                payload={"artifacts": artifacts},
            )
            logger.info(
                "Registered MeetingDigestBot publication for Loom %s as Telegram message %s",
                getattr(meeting, "loom_video_id", None),
                telegram_result.get("message_id"),
            )
            return result
        except Exception as exc:
            logger.warning(
                "Failed to register MeetingDigestBot publication for Loom %s after Telegram message %s: %s",
                getattr(meeting, "loom_video_id", None),
                telegram_result.get("message_id"),
                exc,
            )
            return {"registered": False, "error": str(exc)}

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loom_automation.integrations.google_workspace import GoogleWorkspacePublisher
from loom_automation.integrations.loom import LoomClient
from loom_automation.integrations.storage import SQLiteStorage
from loom_automation.integrations.telegram import TelegramNotifier
from loom_automation.models import DailyDigestRequest, LoomImportRequest, ProcessFolderRequest, ProcessMeetingRequest
from loom_automation.modules.collector import LoomCollector
from loom_automation.modules.summarizer import Summarizer
from loom_automation.modules.telegram_reporter import TelegramReporter
from loom_automation.modules.transcript_processor import TranscriptProcessor
from loom_automation.modules.transcriber import Transcriber
from loom_automation.pipelines.discord_loom import DiscordLoomPipeline


@dataclass
class AutomationWorkflow:
    loom_client: LoomClient
    storage: SQLiteStorage
    google_publisher: GoogleWorkspacePublisher
    telegram_notifier: TelegramNotifier

    def _resolve_llm_provider(self) -> str:
        provider = getattr(self.loom_client, "llm_provider", None)
        if provider:
            return provider
        if getattr(self.loom_client, "local_llm_command", None):
            return "local"
        if getattr(self.loom_client, "llm_api_key", None) or getattr(self.loom_client, "openai_api_key", None):
            return "openai"
        return "auto"

    def _resolve_llm_api_key(self) -> str | None:
        return getattr(self.loom_client, "llm_api_key", None) or getattr(self.loom_client, "openai_api_key", None)

    def _resolve_llm_base_url(self) -> str | None:
        return getattr(self.loom_client, "llm_base_url", None) or getattr(self.loom_client, "openai_base_url", None)

    def _resolve_llm_model(self) -> str:
        return (
            getattr(self.loom_client, "llm_model", None)
            or getattr(self.loom_client, "openai_model", None)
            or "gpt-4.1-mini"
        )

    def _build_discord_loom_pipeline(self) -> DiscordLoomPipeline:
        return DiscordLoomPipeline(
            collector=LoomCollector(
                use_selenium_fallback=self.loom_client.use_selenium_fallback,
                library_url=getattr(self.loom_client, "library_url", "https://www.loom.com/library"),
                loom_title_include_keywords=getattr(self.loom_client, "loom_title_include_keywords", ""),
                loom_title_exclude_keywords=getattr(self.loom_client, "loom_title_exclude_keywords", ""),
                loom_email=getattr(self.loom_client, "email", None),
                loom_password=getattr(self.loom_client, "password", None),
                headless=getattr(self.loom_client, "headless", True),
            ),
            transcriber=Transcriber(
                openai_api_key=getattr(self.loom_client, "openai_api_key", None),
                openai_base_url=getattr(self.loom_client, "openai_base_url", None),
                openai_transcription_model=getattr(self.loom_client, "openai_transcription_model", "gpt-4o-mini-transcribe"),
                local_whisper_command=getattr(self.loom_client, "local_whisper_command", None),
                local_whisper_model=getattr(self.loom_client, "local_whisper_model", "medium"),
                prefer_local_whisper_for_local_files=getattr(self.loom_client, "prefer_local_whisper_for_local_files", True),
            ),
            transcript_processor=TranscriptProcessor(
                enabled=getattr(self.loom_client, "transcript_preprocess_enabled", True),
                prompt_routes_path=getattr(self.loom_client, "prompt_routes_path", "promts/prompt_routes.json"),
                default_prompt_path=getattr(self.loom_client, "default_transcript_prompt_path", "promts/promts_transcription.txt"),
                llm_provider=self._resolve_llm_provider(),
                api_key=self._resolve_llm_api_key(),
                base_url=self._resolve_llm_base_url(),
                model=self._resolve_llm_model(),
                local_llm_command=getattr(self.loom_client, "local_llm_command", None),
                timeout_seconds=getattr(self.loom_client, "llm_timeout_seconds", 120),
            ),
            summarizer=Summarizer(
                llm_provider=self._resolve_llm_provider(),
                openai_api_key=self._resolve_llm_api_key(),
                openai_base_url=self._resolve_llm_base_url(),
                openai_model=self._resolve_llm_model(),
                local_llm_command=getattr(self.loom_client, "local_llm_command", None),
                timeout_seconds=getattr(self.loom_client, "llm_timeout_seconds", 120),
            ),
            telegram_reporter=TelegramReporter(),
            storage=self.storage,
            google_publisher=self.google_publisher,
            telegram_notifier=self.telegram_notifier,
        )

    def _override_runtime(self, **overrides: Any) -> dict[str, Any]:
        previous: dict[str, Any] = {}
        for key, value in overrides.items():
            previous[key] = getattr(self.loom_client, key)
            setattr(self.loom_client, key, value)
        return previous

    def _restore_runtime(self, previous: dict[str, Any]) -> None:
        for key, value in previous.items():
            setattr(self.loom_client, key, value)

    def _log_run(
        self,
        *,
        run_type: str,
        initiated_by: str,
        started_at: datetime,
        status: str,
        summary: dict[str, Any],
    ) -> None:
        self.storage.create_run_log(
            run_type=run_type,
            initiated_by=initiated_by,
            status=status,
            started_at=started_at.isoformat(),
            finished_at=datetime.utcnow().isoformat(),
            summary=summary,
        )

    def process_meeting(self, request: ProcessMeetingRequest, initiated_by: str = "manual") -> dict:
        started_at = datetime.utcnow()
        overrides = {}
        if request.llm_provider:
            overrides["llm_provider"] = request.llm_provider
        if request.transcript_preprocess_enabled is not None:
            overrides["transcript_preprocess_enabled"] = request.transcript_preprocess_enabled
        previous = self._override_runtime(**overrides) if overrides else {}
        try:
            result = self._build_discord_loom_pipeline().run(request)
            self._log_run(
                run_type="process_meeting",
                initiated_by=initiated_by,
                started_at=started_at,
                status="success",
                summary={
                    "collector_source": request.collector_source,
                    "meeting_type": request.meeting_type,
                    "loom_video_id": result.get("meeting", {}).get("loom_video_id"),
                    "title": result.get("meeting", {}).get("title"),
                    "telegram_sent": result.get("telegram", {}).get("sent"),
                },
            )
        except Exception as exc:
            self._log_run(
                run_type="process_meeting",
                initiated_by=initiated_by,
                started_at=started_at,
                status="error",
                summary={
                    "collector_source": request.collector_source,
                    "meeting_type": request.meeting_type,
                    "error": str(exc),
                },
            )
            raise
        finally:
            if previous:
                self._restore_runtime(previous)
        result["next_step"] = "Automate Loom discovery and external STT to remove manual transcript input."
        return result

    def process_folder(self, request: ProcessFolderRequest, initiated_by: str = "manual") -> dict:
        started_at = datetime.utcnow()
        overrides = {}
        if request.llm_provider:
            overrides["llm_provider"] = request.llm_provider
        if request.transcript_preprocess_enabled is not None:
            overrides["transcript_preprocess_enabled"] = request.transcript_preprocess_enabled
        previous = self._override_runtime(**overrides) if overrides else {}
        try:
            result = self._build_discord_loom_pipeline().run_folder(request)
            self._log_run(
                run_type="process_folder",
                initiated_by=initiated_by,
                started_at=started_at,
                status="success",
                summary={
                    "folder_path": request.folder_path,
                    "meeting_type": request.meeting_type,
                    "processed_count": result.get("processed_count", 0),
                },
            )
        except Exception as exc:
            self._log_run(
                run_type="process_folder",
                initiated_by=initiated_by,
                started_at=started_at,
                status="error",
                summary={
                    "folder_path": request.folder_path,
                    "meeting_type": request.meeting_type,
                    "error": str(exc),
                },
            )
            raise
        finally:
            if previous:
                self._restore_runtime(previous)
        result["next_step"] = "Connect watched-folder automation or scheduler for recurring local imports."
        return result

    def import_latest_loom(self, request: LoomImportRequest, initiated_by: str = "manual") -> dict:
        started_at = datetime.utcnow()
        overrides = {}
        if request.llm_provider:
            overrides["llm_provider"] = request.llm_provider
        if request.transcript_preprocess_enabled is not None:
            overrides["transcript_preprocess_enabled"] = request.transcript_preprocess_enabled
        if request.title_include_keywords:
            overrides["loom_title_include_keywords"] = ",".join(request.title_include_keywords)
        if request.title_exclude_keywords:
            overrides["loom_title_exclude_keywords"] = ",".join(request.title_exclude_keywords)
        previous = self._override_runtime(**overrides) if overrides else {}
        try:
            result = self._build_discord_loom_pipeline().run_loom_import(request)
            processed = result.get("results", [])
            self._log_run(
                run_type="loom_import",
                initiated_by=initiated_by,
                started_at=started_at,
                status="success",
                summary={
                    "meeting_type": request.meeting_type,
                    "processed_count": result.get("processed_count", 0),
                    "limit": request.limit,
                    "titles": [item.get("meeting", {}).get("title") for item in processed[:5]],
                },
            )
        except Exception as exc:
            self._log_run(
                run_type="loom_import",
                initiated_by=initiated_by,
                started_at=started_at,
                status="error",
                summary={
                    "meeting_type": request.meeting_type,
                    "limit": request.limit,
                    "error": str(exc),
                },
            )
            raise
        finally:
            if previous:
                self._restore_runtime(previous)
        result["next_step"] = "Tune transcript selectors against your Loom workspace UI and then schedule recurring imports."
        return result

    def build_daily_digest(self, request: DailyDigestRequest, initiated_by: str = "manual") -> dict:
        started_at = datetime.utcnow()
        rows = self.storage.list_meeting_records_for_day(request.report_date.isoformat())
        payload = []
        for loom_video_id, title, source_url, artifacts_json in rows:
            payload.append(
                {
                    "loom_video_id": loom_video_id,
                    "title": title,
                    "source_url": source_url,
                    "artifacts": json.loads(artifacts_json),
                }
            )

        summarizer = Summarizer(
            llm_provider=self._resolve_llm_provider(),
            openai_api_key=self._resolve_llm_api_key(),
            openai_base_url=self._resolve_llm_base_url(),
            openai_model=self._resolve_llm_model(),
            local_llm_command=getattr(self.loom_client, "local_llm_command", None),
            timeout_seconds=getattr(self.loom_client, "llm_timeout_seconds", 120),
        )
        digest = summarizer.summarize_daily(request.report_date, payload)
        reporter = TelegramReporter()
        digest.telegram_digest = reporter.append_daily_links(
            digest.telegram_digest,
            items=payload,
            google_doc_url=self.google_publisher.current_doc_url(),
        )

        try:
            telegram_result = self.telegram_notifier.send_digest(digest.telegram_digest)
            result = {
                "items": payload,
                "digest": digest.model_dump(),
                "telegram": telegram_result,
            }
            self._log_run(
                run_type="daily_digest",
                initiated_by=initiated_by,
                started_at=started_at,
                status="success",
                summary={
                    "report_date": request.report_date.isoformat(),
                    "items_count": len(payload),
                    "telegram_sent": telegram_result.get("sent"),
                    "telegram_message_id": telegram_result.get("message_id"),
                },
            )
            return result
        except Exception as exc:
            self._log_run(
                run_type="daily_digest",
                initiated_by=initiated_by,
                started_at=started_at,
                status="error",
                summary={
                    "report_date": request.report_date.isoformat(),
                    "items_count": len(payload),
                    "error": str(exc),
                },
            )
            raise

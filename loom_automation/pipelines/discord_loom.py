from __future__ import annotations

from dataclasses import dataclass

from loom_automation.integrations.google_workspace import GoogleWorkspacePublisher
from loom_automation.integrations.storage import SQLiteStorage
from loom_automation.integrations.telegram import TelegramNotifier
from loom_automation.models import LoomImportRequest, ProcessFolderRequest, ProcessMeetingRequest
from loom_automation.modules.collector import LoomCollector
from loom_automation.modules.summarizer import Summarizer
from loom_automation.modules.telegram_reporter import TelegramReporter
from loom_automation.modules.transcript_processor import TranscriptProcessor
from loom_automation.modules.transcriber import Transcriber


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

    def run(self, request: ProcessMeetingRequest) -> dict:
        collected = self._collect(request)
        meeting = self.collector.to_meeting_metadata(collected, meeting_type=request.meeting_type)
        transcript = self.transcriber.build_transcript(collected)
        transcript_text = self.transcript_processor.process(
            transcript.transcript_text,
            meeting_title=meeting.title,
        )
        artifacts = self.summarizer.summarize(
            transcript_text,
            meeting_title=meeting.title,
            meeting_type=meeting.meeting_type,
        )
        if not artifacts.telegram_digest:
            artifacts.telegram_digest = self.telegram_reporter.render_meeting_digest(meeting, artifacts)

        self.storage.upsert_meeting(meeting, transcript_text)
        self.storage.save_artifacts(meeting.loom_video_id, artifacts)

        google_result = self.google_publisher.publish_meeting_artifacts(meeting, artifacts, transcript_text)
        artifacts.telegram_digest = self.telegram_reporter.append_meeting_links(
            artifacts.telegram_digest,
            meeting=meeting,
            google_doc_url=google_result.get("google_doc_url") or self.google_publisher.current_doc_url(),
            doc_section_title=self.google_publisher.section_title(meeting),
            transcript_doc_url=google_result.get("transcript_doc_url") or self.google_publisher.current_transcript_doc_url(),
            transcript_section_title=self.google_publisher.transcript_section_title(meeting),
        )
        telegram_result = self.telegram_notifier.send_digest(artifacts.telegram_digest)

        return {
            "pipeline": "discord-loom",
            "transcript_source": transcript.source,
            "meeting": meeting.model_dump(),
            "artifacts": artifacts.model_dump(),
            "google": google_result,
            "telegram": telegram_result,
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
            transcript_text = self.transcript_processor.process(
                transcript.transcript_text,
                meeting_title=meeting.title,
            )
            artifacts = self.summarizer.summarize(
                transcript_text,
                meeting_title=meeting.title,
                meeting_type=meeting.meeting_type,
            )
            if not artifacts.telegram_digest:
                artifacts.telegram_digest = self.telegram_reporter.render_meeting_digest(meeting, artifacts)

            self.storage.upsert_meeting(meeting, transcript_text)
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
            transcript_text = self.transcript_processor.process(
                transcript.transcript_text,
                meeting_title=meeting.title,
            )
            artifacts = self.summarizer.summarize(
                transcript_text,
                meeting_title=meeting.title,
                meeting_type=meeting.meeting_type,
            )
            if not artifacts.telegram_digest:
                artifacts.telegram_digest = self.telegram_reporter.render_meeting_digest(meeting, artifacts)

            self.storage.upsert_meeting(meeting, transcript_text)
            self.storage.save_artifacts(meeting.loom_video_id, artifacts)

            google_result = self.google_publisher.publish_meeting_artifacts(meeting, artifacts, transcript_text)
            artifacts.telegram_digest = self.telegram_reporter.append_meeting_links(
                artifacts.telegram_digest,
                meeting=meeting,
                google_doc_url=google_result.get("google_doc_url") or self.google_publisher.current_doc_url(),
                doc_section_title=self.google_publisher.section_title(meeting),
                transcript_doc_url=google_result.get("transcript_doc_url") or self.google_publisher.current_transcript_doc_url(),
                transcript_section_title=self.google_publisher.transcript_section_title(meeting),
            )
            telegram_result = self.telegram_notifier.send_digest(artifacts.telegram_digest)
            results.append(
                {
                    "meeting": meeting.model_dump(),
                    "transcript_source": transcript.source,
                    "artifacts": artifacts.model_dump(),
                    "google": google_result,
                    "telegram": telegram_result,
                }
            )

        return {
            "pipeline": "loom-auto-import",
            "processed_count": len(results),
            "collection_debug": collection_debug,
            "results": results,
        }

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

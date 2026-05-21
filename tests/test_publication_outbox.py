from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from loom_automation.integrations.storage import SQLiteStorage
from loom_automation.models import MeetingArtifacts, MeetingMetadata
from loom_automation.modules.telegram_reporter import TelegramReporter
from loom_automation.pipelines.discord_loom import DiscordLoomPipeline


class PublicationOutboxTests(unittest.TestCase):
    def make_storage(self) -> SQLiteStorage:
        tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmpdir.cleanup)
        return SQLiteStorage(f"sqlite:///{Path(tmpdir.name) / 'test.db'}")

    def test_legacy_meetings_are_not_retried_without_publication_record(self) -> None:
        storage = self.make_storage()
        meeting = MeetingMetadata(
            loom_video_id="loom-1",
            source_url="https://www.loom.com/share/loom-1",
            title="#task_demo legacy",
            meeting_type="discord-sync",
        )
        storage.upsert_meeting(meeting, "transcript")
        storage.save_artifacts(meeting.loom_video_id, MeetingArtifacts(summary="summary"))

        self.assertEqual(storage.list_unpublished_meeting_records(), [])

    def test_failed_publication_is_available_for_retry_and_preserves_successful_steps(self) -> None:
        storage = self.make_storage()
        meeting = MeetingMetadata(
            loom_video_id="loom-2",
            source_url="https://www.loom.com/share/loom-2",
            title="#task_demo retry",
            meeting_type="discord-sync",
        )
        storage.upsert_meeting(meeting, "transcript")
        storage.save_artifacts(meeting.loom_video_id, MeetingArtifacts(summary="summary"))

        storage.begin_meeting_publication(meeting.loom_video_id)
        storage.update_meeting_publication_step(
            meeting.loom_video_id,
            step="google",
            status="success",
            result={"google_doc_url": "https://docs.google.com/document/d/doc/edit"},
        )
        storage.update_meeting_publication_step(
            meeting.loom_video_id,
            step="telegram",
            status="error",
            result={"sent": False},
            error="Telegram failed",
        )
        storage.complete_meeting_publication(meeting.loom_video_id, status="error", error="Telegram failed")

        retry_records = storage.list_unpublished_meeting_records()
        self.assertEqual(len(retry_records), 1)
        self.assertEqual(retry_records[0]["loom_video_id"], "loom-2")

        publication = storage.get_meeting_publication("loom-2")
        self.assertIsNotNone(publication)
        self.assertEqual(publication["status"], "error")
        self.assertEqual(publication["google_status"], "success")
        self.assertEqual(publication["google_result"]["google_doc_url"], "https://docs.google.com/document/d/doc/edit")
        self.assertEqual(publication["telegram_status"], "error")

    def test_retry_reuses_existing_telegram_message_when_only_register_failed(self) -> None:
        storage = self.make_storage()
        meeting = MeetingMetadata(
            loom_video_id="loom-3",
            source_url="https://www.loom.com/share/loom-3",
            title="#task_demo register retry",
            meeting_type="discord-sync",
        )
        artifacts = MeetingArtifacts(summary="summary", telegram_digest="digest")
        storage.upsert_meeting(meeting, "transcript")
        storage.save_artifacts(meeting.loom_video_id, artifacts)
        storage.begin_meeting_publication(meeting.loom_video_id)
        storage.update_meeting_publication_step(
            meeting.loom_video_id,
            step="google",
            status="success",
            result={
                "google_doc_url": "https://docs.google.com/document/d/doc/edit",
                "transcript_doc_url": "https://docs.google.com/document/d/transcript/edit",
            },
        )
        storage.update_meeting_publication_step(
            meeting.loom_video_id,
            step="telegram",
            status="success",
            result={"sent": True, "message_id": 123, "chat_id": -100},
        )
        storage.update_meeting_publication_step(
            meeting.loom_video_id,
            step="register",
            status="error",
            result={"registered": False, "error": "register failed"},
            error="register failed",
        )
        storage.complete_meeting_publication(meeting.loom_video_id, status="error", error="register failed")

        telegram = FakeTelegramNotifier()
        digest_bot = FakeMeetingDigestBot()
        pipeline = DiscordLoomPipeline(
            collector=None,
            transcriber=None,
            transcript_processor=None,
            summarizer=None,
            telegram_reporter=TelegramReporter(),
            storage=storage,
            google_publisher=FakeGooglePublisher(),
            telegram_notifier=telegram,
            meeting_digest_bot=digest_bot,
        )

        result = pipeline._publish_saved_meeting(
            meeting=meeting,
            artifacts=artifacts,
            raw_transcript_text="transcript",
            retry=True,
        )

        self.assertEqual(telegram.calls, 0)
        self.assertEqual(digest_bot.calls, 1)
        self.assertEqual(digest_bot.last_telegram_result["message_id"], 123)
        self.assertEqual(result["publication_status"], "published")


class FakeGooglePublisher:
    def publish_meeting_artifacts(self, *_args, **_kwargs):
        raise AssertionError("Google should be reused from publication outbox")

    def current_doc_url(self):
        return "https://docs.google.com/document/d/doc/edit"

    def current_transcript_doc_url(self):
        return "https://docs.google.com/document/d/transcript/edit"

    def section_title(self, meeting):
        return f"Meeting Note: {meeting.title}"

    def transcript_section_title(self, meeting):
        return f"Transcript: {meeting.title}"


class FakeTelegramNotifier:
    def __init__(self) -> None:
        self.calls = 0

    def send_digest(self, _text: str):
        self.calls += 1
        return {"sent": True, "message_id": 999, "chat_id": -100}


class FakeMeetingDigestBot:
    enabled = True

    def __init__(self) -> None:
        self.calls = 0
        self.last_telegram_result = None

    def register_meeting_publication(self, *, telegram_result, **_kwargs):
        self.calls += 1
        self.last_telegram_result = telegram_result
        return {"registered": True, "record": {"post_url": "https://t.me/c/100/123"}}


if __name__ == "__main__":
    unittest.main()

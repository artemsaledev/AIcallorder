from __future__ import annotations

from datetime import date, datetime
import unittest

from loom_automation.integrations.meeting_digest_bot import _json_safe, extract_source_tags


class MeetingDigestBotTagTests(unittest.TestCase):
    def test_extracts_tags_from_title_and_payload(self) -> None:
        tags = extract_source_tags(
            "#task_discussion CRM checklist sync",
            {"artifacts": {"tags": ["#task_demo"], "summary": "Проверили демо #task_demo"}},
        )
        self.assertEqual(tags, ["#task_discussion", "#task_demo"])

    def test_keeps_daily_tag_for_receiver_to_exclude(self) -> None:
        tags = extract_source_tags("#daily #task_discussion")
        self.assertEqual(tags, ["#daily", "#task_discussion"])

    def test_json_safe_converts_dates_recursively(self) -> None:
        payload = {
            "date": date(2026, 5, 14),
            "nested": [{"at": datetime(2026, 5, 14, 9, 30)}],
        }
        self.assertEqual(
            _json_safe(payload),
            {
                "date": "2026-05-14",
                "nested": [{"at": "2026-05-14T09:30:00"}],
            },
        )


if __name__ == "__main__":
    unittest.main()

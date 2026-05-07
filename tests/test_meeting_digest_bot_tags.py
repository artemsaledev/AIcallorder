from __future__ import annotations

import unittest

from loom_automation.integrations.meeting_digest_bot import extract_source_tags


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


if __name__ == "__main__":
    unittest.main()

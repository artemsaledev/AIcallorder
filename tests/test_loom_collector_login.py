from __future__ import annotations

import unittest
from unittest.mock import patch

from loom_automation.modules.collector import LoomCollector


class _FakeDriver:
    def __init__(self, *, url: str, title: str, visible_text: str = "", page_source: str = "") -> None:
        self.current_url = url
        self.title = title
        self._visible_text = visible_text
        self.page_source = page_source
        self.window_handles = ["main"]
        self.current_window_handle = "main"
        self.switch_to = self

    def window(self, _handle: str) -> None:
        return None

    def get(self, url: str) -> None:
        self.current_url = url

    def execute_script(self, script: str):
        if "document.readyState" in script:
            return "complete"
        if "body.innerText" in script:
            return self._visible_text
        return None


class LoomCollectorLoginTests(unittest.TestCase):
    def test_nested_library_url_is_treated_as_library(self) -> None:
        collector = LoomCollector()

        self.assertTrue(collector._is_library_url("https://www.loom.com/looms/videos/folder-abc"))
        self.assertTrue(
            collector._looks_like_library_page(
                "https://www.loom.com/looms/videos/folder-abc",
                title="Videos | Library | Loom",
            )
        )

    def test_blocker_detection_ignores_verified_library_page(self) -> None:
        collector = LoomCollector()
        driver = _FakeDriver(
            url="https://www.loom.com/looms/videos/folder-abc",
            title="Videos | Library | Loom",
            visible_text="Loom Library Videos",
            page_source="<html><body>otp verification</body></html>",
        )

        self.assertIsNone(collector._detect_login_blocker(driver))

    def test_blocker_detection_flags_verification_challenge(self) -> None:
        collector = LoomCollector()
        driver = _FakeDriver(
            url="https://id.atlassian.com/login/verify",
            title="Verify your identity",
            visible_text="Enter the code we sent to your email to continue.",
        )

        blocker = collector._detect_login_blocker(driver)

        self.assertIsNotNone(blocker)
        self.assertIn("email verification or 2FA challenge", blocker)

    def test_select_transcript_candidate_prefers_real_transcript_block(self) -> None:
        collector = LoomCollector()

        selected = collector._select_transcript_candidate(
            [
                "Transcript\nComments\nShare",
                "00:01 Artem: Start the sync\n00:14 Team: Confirmed the plan\n00:35 Artem: Next step is Payments.pro handoff",
                "New video\nNew folder\nUpload date",
            ]
        )

        self.assertIn("Payments.pro handoff", selected)
        self.assertNotIn("New folder", selected)

    def test_extract_virtualized_transcript_rows_scrolls_and_merges_visible_batches(self) -> None:
        collector = LoomCollector()
        batches = [
            ["0:02\nFirst segment", "0:26\nSecond segment"],
            ["0:26\nSecond segment", "0:40\nThird segment"],
            ["0:40\nThird segment", "1:05\nFourth segment"],
        ]
        state = {"index": 0}

        collector._reset_transcript_scroll = lambda _driver: None
        collector._read_visible_transcript_rows = lambda _driver: batches[state["index"]]

        def _scroll(_driver) -> bool:
            if state["index"] >= len(batches) - 1:
                return False
            state["index"] += 1
            return True

        collector._scroll_transcript_container = _scroll

        with patch("loom_automation.modules.collector.time.sleep", return_value=None):
            transcript = collector._extract_virtualized_transcript_rows(object())

        self.assertEqual(
            transcript,
            "0:02\nFirst segment\n0:26\nSecond segment\n0:40\nThird segment\n1:05\nFourth segment",
        )

    def test_extract_transcript_prefers_copy_button_payload(self) -> None:
        collector = LoomCollector()
        driver = _FakeDriver(
            url="https://www.loom.com/share/example-video",
            title="Example video | Loom",
            visible_text="Transcript panel is visible",
        )

        collector._detect_login_blocker = lambda _driver: None
        collector._open_transcript_panel = lambda _driver, _wait: True
        collector._extract_transcript_via_copy_button = lambda _driver, _wait: "0:03\nFull copied transcript"
        collector._extract_virtualized_transcript_rows = lambda _driver: ""
        collector._extract_transcript_text_from_dom = lambda _driver: ""

        transcript, title = collector._extract_transcript(driver, object(), driver.current_url)

        self.assertEqual(transcript, "0:03\nFull copied transcript")
        self.assertEqual(title, "Example video")

    def test_extract_timestamped_transcript_from_visible_text_discards_toolbar_noise(self) -> None:
        collector = LoomCollector()

        transcript = collector._extract_timestamped_transcript_from_text(
            """
            Edit
            Activity
            Generate
            Transcript
            Settings
            Copy
            Correct
            Download
            Language
            Search
            00:03 Да, Миша, може, нам ще треба, ну, щоб він в курсі був.
            00:20 Давайте просто тоді позапитуємо Стаса, як він там налагодив.
            00:48 Ігор озвучував питання вчора, тому треба синхронізувати процес.
            Contact Sales
            Try it out
            """
        )

        self.assertIn("00:03 Да, Миша", transcript)
        self.assertIn("00:48 Ігор", transcript)
        self.assertNotIn("Copy", transcript)
        self.assertNotIn("Contact Sales", transcript)

    def test_extract_transcript_falls_back_to_visible_page_text_when_copy_is_empty(self) -> None:
        collector = LoomCollector()
        driver = _FakeDriver(
            url="https://www.loom.com/share/example-video",
            title="Example video | Loom",
            visible_text="""
                Edit
                Activity
                Generate
                Transcript
                Settings
                Copy
                Correct
                Download
                Language
                Search
                00:03 First spoken point
                00:20 Second spoken point
                00:48 Third spoken point
            """,
        )

        collector._detect_login_blocker = lambda _driver: None
        collector._open_transcript_panel = lambda _driver, _wait: True
        collector._extract_transcript_via_copy_button = lambda _driver, _wait: ""
        collector._extract_transcript_from_timestamped_blocks = lambda _driver: ""
        collector._extract_virtualized_transcript_rows = lambda _driver: ""
        collector._extract_transcript_text_from_dom = lambda _driver: ""

        transcript, _title = collector._extract_transcript(driver, object(), driver.current_url)

        self.assertIn("00:03 First spoken point", transcript)
        self.assertIn("00:48 Third spoken point", transcript)

    def test_read_all_library_links_includes_share_urls_from_html(self) -> None:
        collector = LoomCollector()
        driver = _FakeDriver(
            url="https://www.loom.com/looms/videos/example-folder",
            title="Videos | Library | Loom",
            page_source="""
                <html>
                  <body>
                    <script>
                      window.__DATA__ = {
                        "items": [
                          {"shareUrl":"https://www.loom.com/share/alpha123"},
                          {"shareUrl":"https://www.loom.com/share/beta456"}
                        ]
                      };
                    </script>
                  </body>
                </html>
            """,
        )
        collector._read_visible_library_links = lambda _driver: ["https://www.loom.com/share/visible789"]

        links = collector._read_all_library_links(driver)

        self.assertEqual(
            links,
            [
                "https://www.loom.com/share/visible789",
                "https://www.loom.com/share/alpha123",
                "https://www.loom.com/share/beta456",
            ],
        )


if __name__ == "__main__":
    unittest.main()

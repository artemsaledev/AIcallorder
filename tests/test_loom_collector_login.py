from __future__ import annotations

import unittest

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

    def execute_script(self, script: str):
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


if __name__ == "__main__":
    unittest.main()

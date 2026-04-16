from __future__ import annotations

import unittest

from loom_automation.modules.transcriber import Transcriber
from loom_automation.modules.transcript_processor import TranscriptProcessor


class TranscriptTextIntegrityTests(unittest.TestCase):
    def test_normalize_transcript_preserves_line_breaks(self) -> None:
        transcriber = Transcriber()

        normalized = transcriber._normalize_transcript(
            "0:02   First line with   extra spaces\r\n\r\n0:26\tSecond line\r\n0:40  Third line"
        )

        self.assertEqual(
            normalized,
            "0:02 First line with extra spaces\n0:26 Second line\n0:40 Third line",
        )

    def test_process_falls_back_to_original_when_cleaned_text_is_lossy(self) -> None:
        processor = TranscriptProcessor(enabled=True)
        original = (
            "0:02\nFirst detailed point\n"
            "0:26\nSecond detailed point\n"
            "0:40\nThird detailed point\n"
            "1:05\nFourth detailed point"
        )
        processor._invoke_llm = lambda **_kwargs: {"cleaned_transcript": "1:05\nFourth detailed point"}

        cleaned = processor.process(original, meeting_title="#daily integrity check")

        self.assertEqual(cleaned, original)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from loom_automation.models import MeetingMetadata, MeetingTranscript


@dataclass
class LoomClient:
    transcript_source: str = "meeting_ai"
    use_selenium_fallback: bool = False
    library_url: str = "https://www.loom.com/library"
    loom_title_include_keywords: str = ""
    loom_title_exclude_keywords: str = ""
    prompt_routes_path: str = "promts/prompt_routes.json"
    transcript_preprocess_enabled: bool = True
    default_transcript_prompt_path: str = "promts/promts_transcription.txt"
    email: str | None = None
    password: str | None = None
    headless: bool = True
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    llm_provider: str = "auto"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: int = 120
    local_llm_command: str | None = None
    local_whisper_command: str | None = None
    local_whisper_model: str = "medium"
    prefer_local_whisper_for_local_files: bool = True

    def parse_video_id(self, loom_url: str) -> str:
        parsed = urlparse(loom_url)
        parts = [part for part in parsed.path.split("/") if part]
        if "share" in parts:
            return parts[-1]
        raise ValueError(f"Unsupported Loom URL format: {loom_url}")

    def load_transcript(
        self,
        loom_video_id: Optional[str] = None,
        loom_url: Optional[str] = None,
        transcript_text: Optional[str] = None,
        title: str = "Loom meeting",
        meeting_type: str = "general",
    ) -> MeetingTranscript:
        if transcript_text:
            resolved_video_id = loom_video_id or (self.parse_video_id(loom_url) if loom_url else "manual-input")
            return MeetingTranscript(
                meeting=MeetingMetadata(
                    loom_video_id=resolved_video_id,
                    source_url=loom_url or resolved_video_id,
                    title=title,
                    meeting_type=meeting_type,
                    recorded_at=datetime.utcnow(),
                ),
                transcript_text=transcript_text,
            )

        raise NotImplementedError(
            "Direct Loom transcript fetching should be implemented through the chosen workspace integration. "
            "Use transcript_text for local testing or keep Selenium as a fallback adapter."
        )

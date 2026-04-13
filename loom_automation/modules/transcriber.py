from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import requests

from loom_automation.modules.collector import CollectedVideo


@dataclass
class TranscriptResult:
    transcript_text: str
    source: str


@dataclass
class Transcriber:
    """
    Transcript strategy for Discord + Loom:
    1. Prefer transcript already available from Loom/UI flow.
    2. Fall back to external STT on downloaded audio.
    """

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    local_whisper_command: str | None = None
    local_whisper_model: str = "medium"
    prefer_local_whisper_for_local_files: bool = True

    def build_transcript(self, video: CollectedVideo) -> TranscriptResult:
        if video.transcript_text:
            return TranscriptResult(
                transcript_text=self._normalize_transcript(video.transcript_text),
                source="loom-transcript",
            )

        if video.audio_source_path:
            if self.prefer_local_whisper_for_local_files:
                local_result = self._transcribe_with_local_whisper(video.audio_source_path)
                if local_result:
                    return local_result

            openai_result = self._transcribe_with_openai(video.audio_source_path)
            if openai_result:
                return openai_result

            local_result = self._transcribe_with_local_whisper(video.audio_source_path)
            if local_result:
                return local_result

        raise ValueError(
            "No transcript text or audio source is available for transcription. "
            "For Loom videos provide transcript_text. For local videos configure LOCAL_WHISPER_COMMAND."
        )

    def _transcribe_with_openai(self, audio_source_path: str) -> TranscriptResult | None:
        if not self.openai_api_key:
            return None

        url = (self.openai_base_url or "https://api.openai.com/v1").rstrip("/") + "/audio/transcriptions"
        with open(audio_source_path, "rb") as audio_file:
            response = requests.post(
                url,
                headers={"Authorization": f"Bearer {self.openai_api_key}"},
                data={"model": self.openai_transcription_model},
                files={"file": (Path(audio_source_path).name, audio_file)},
                timeout=300,
            )
        response.raise_for_status()
        payload = response.json()
        text = payload.get("text", "").strip()
        if not text:
            raise ValueError("OpenAI transcription returned an empty transcript.")
        return TranscriptResult(
            transcript_text=self._normalize_transcript(text),
            source=f"openai:{self.openai_transcription_model}",
        )

    def _transcribe_with_local_whisper(self, audio_source_path: str) -> TranscriptResult | None:
        bundled_result = self._transcribe_with_bundled_faster_whisper(audio_source_path)
        if bundled_result:
            return bundled_result

        if not self.local_whisper_command:
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            command = [
                self.local_whisper_command,
                audio_source_path,
                "--output_format",
                "txt",
                "--output_dir",
                tmpdir,
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Local whisper transcription failed.")

            transcript_path = Path(tmpdir) / f"{Path(audio_source_path).stem}.txt"
            if not transcript_path.exists():
                raise FileNotFoundError(f"Expected transcript file not found: {transcript_path}")

            text = transcript_path.read_text(encoding="utf-8").strip()
            if not text:
                raise ValueError("Local whisper transcription returned an empty transcript.")
            return TranscriptResult(
                transcript_text=self._normalize_transcript(text),
                source="local-whisper",
            )

    def _transcribe_with_bundled_faster_whisper(self, audio_source_path: str) -> TranscriptResult | None:
        dep_roots = [Path.cwd() / ".pydeps", Path.cwd() / ".vendor"]
        active_dep_root = next((path for path in dep_roots if path.exists()), None)
        if active_dep_root is None:
            return None

        if str(active_dep_root) not in sys.path:
            sys.path.insert(0, str(active_dep_root))

        try:
            from faster_whisper import WhisperModel
        except Exception:
            return None

        model = WhisperModel(self.local_whisper_model, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_source_path, vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            raise ValueError("Bundled faster-whisper returned an empty transcript.")
        return TranscriptResult(
            transcript_text=self._normalize_transcript(text),
            source=f"bundled-faster-whisper:{self.local_whisper_model}",
        )

    def _normalize_transcript(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        replacements: list[tuple[str, str]] = [
            (r"\bбитрик[сc]\b", "Bitrix"),
            (r"\bбэтрикс\b", "Bitrix"),
            (r"\bбитрекс\b", "Bitrix"),
            (r"\b1\s*с\b", "1С"),
            (r"\bодин\s*эс\b", "1С"),
            (r"\bсrm\b", "CRM"),
            (r"\bцрм\b", "CRM"),
            (r"\bси эр эм\b", "CRM"),
            (r"\bартику\b", "артикул"),
            (r"\bартикулы\b", "артикулы"),
            (r"\bмаркувания\b", "маркировки"),
            (r"\bэтикетки\b", "этикетки"),
            (r"\bгрудить\b", "грузить"),
            (r"\bбренд(а|ов|ы)?\b", lambda m: m.group(0).lower()),
        ]
        for pattern, replacement in replacements:
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bbitrix24\b", "Bitrix24", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bтелеграм\b", "Telegram", normalized, flags=re.IGNORECASE)
        return normalized

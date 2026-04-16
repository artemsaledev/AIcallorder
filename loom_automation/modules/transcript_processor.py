from __future__ import annotations

from dataclasses import dataclass
import json
import re
import shlex
import subprocess
from typing import Any

import requests

from loom_automation.prompt_routing import load_prompt_routing_config, load_prompt_text


TRANSCRIPT_CLEANUP_SYSTEM_PROMPT = """
Ты редактор транскриптов рабочих встреч.

Твоя задача:
- исправить явные ошибки распознавания речи;
- убрать бессмысленные повторы и словесный мусор;
- сохранить исходный смысл разговора без резюмирования;
- оформить текст читабельно по абзацам;
- сохранить важные технические термины, названия систем, имена и договоренности;
- не выдумывать новых фактов.

Верни только JSON:
{
  "cleaned_transcript": "..."
}
""".strip()


@dataclass
class TranscriptProcessor:
    enabled: bool = True
    prompt_routes_path: str = "promts/prompt_routes.json"
    default_prompt_path: str = "promts/promts_transcription.txt"
    llm_provider: str = "auto"
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4.1-mini"
    local_llm_command: str | None = None
    timeout_seconds: int = 120

    def process(self, transcript_text: str, *, meeting_title: str) -> str:
        if not self.enabled or not transcript_text.strip():
            return transcript_text

        prompt_text = self._resolve_prompt_for_title(meeting_title)
        user_prompt = (
            f"{prompt_text}\n\n"
            f"Название видео: {meeting_title}\n\n"
            f"Транскрипт:\n{transcript_text[:30000]}"
        )
        payload = self._invoke_llm(
            system_prompt=TRANSCRIPT_CLEANUP_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        if not payload:
            return transcript_text
        cleaned = str(payload.get("cleaned_transcript", "")).strip()
        if not cleaned:
            return transcript_text
        normalized = self._normalize_cleaned_transcript(cleaned)
        if self._looks_lossy(original=transcript_text, cleaned=normalized):
            return transcript_text
        return normalized

    def _resolve_prompt_for_title(self, title: str) -> str:
        routing = load_prompt_routing_config(self.prompt_routes_path)
        route = routing.resolve_route(title)
        if route:
            return load_prompt_text(route.prompt_path)
        return load_prompt_text(self.default_prompt_path)

    def _invoke_llm(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        provider = (self.llm_provider or "auto").strip().lower()
        if provider == "local":
            return self._invoke_local_llm(system_prompt=system_prompt, user_prompt=user_prompt)
        if provider in {"openai", "compatible", "cloud"}:
            return self._invoke_openai(system_prompt=system_prompt, user_prompt=user_prompt)
        if self.local_llm_command:
            result = self._invoke_local_llm(system_prompt=system_prompt, user_prompt=user_prompt)
            if result is not None:
                return result
        if self.api_key:
            return self._invoke_openai(system_prompt=system_prompt, user_prompt=user_prompt)
        return None

    def _invoke_local_llm(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        if not self.local_llm_command:
            return None
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        command = self._split_command(self.local_llm_command)
        if not command:
            return None
        try:
            completed = subprocess.run(
                command,
                input=full_prompt,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="ignore",
                timeout=self.timeout_seconds,
                check=False,
            )
        except Exception:
            return None
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        return self._extract_json_object(completed.stdout)

    def _invoke_openai(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        base_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except Exception:
            return None
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return None
        return self._extract_json_object(content)

    def _extract_json_object(self, raw_text: str) -> dict[str, Any] | None:
        text = self._sanitize_output(raw_text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _split_command(self, command: str | None) -> list[str]:
        if not command:
            return []
        try:
            parts = shlex.split(command, posix=False)
        except Exception:
            return [command]
        cleaned = []
        for part in parts:
            if len(part) >= 2 and part[0] == part[-1] == '"':
                cleaned.append(part[1:-1])
            else:
                cleaned.append(part)
        if cleaned and cleaned[0].lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", *cleaned]
        return cleaned

    def _sanitize_output(self, raw_text: str) -> str:
        text = raw_text or ""
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
        text = text.replace("```json", "").replace("```", "")
        return text.strip()

    def _normalize_cleaned_transcript(self, text: str) -> str:
        paragraphs = []
        for block in str(text).splitlines():
            cleaned = re.sub(r"\s+", " ", block).strip()
            if cleaned:
                paragraphs.append(cleaned)
        return "\n".join(paragraphs).strip()

    def _looks_lossy(self, *, original: str, cleaned: str) -> bool:
        original_text = (original or "").strip()
        cleaned_text = (cleaned or "").strip()
        if not original_text or not cleaned_text:
            return False

        if len(cleaned_text) < max(200, int(len(original_text) * 0.55)):
            return True

        original_lines = [line.strip() for line in original_text.splitlines() if line.strip()]
        cleaned_lines = [line.strip() for line in cleaned_text.splitlines() if line.strip()]
        if len(original_lines) >= 6 and len(cleaned_lines) <= max(2, len(original_lines) // 4):
            return True

        timestamp_pattern = r"\b\d{1,2}:\d{2}(?::\d{2})?\b"
        original_timestamps = len(re.findall(timestamp_pattern, original_text))
        cleaned_timestamps = len(re.findall(timestamp_pattern, cleaned_text))
        if original_timestamps >= 3 and cleaned_timestamps < max(1, original_timestamps // 3):
            return True

        return False

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from typing import Any

import requests


def _normalize_base_url(base_url: str | None) -> str:
    if not base_url:
        return ""
    return base_url.rstrip("/")


def build_telegram_post_url(
    *,
    chat_id: str | int | None,
    message_id: str | int | None,
    channel_username: str | None = None,
) -> str | None:
    if not chat_id or not message_id:
        return None
    if channel_username:
        slug = channel_username.strip().lstrip("@")
        if slug:
            return f"https://t.me/{slug}/{message_id}"
    raw_chat_id = str(chat_id).strip()
    if raw_chat_id.startswith("-100"):
        internal_chat_id = raw_chat_id[4:]
    elif raw_chat_id.startswith("-"):
        internal_chat_id = raw_chat_id[1:]
    else:
        internal_chat_id = raw_chat_id
    return f"https://t.me/c/{internal_chat_id}/{message_id}"


def extract_source_tags(*values: Any) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            nested_values: list[Any] = list(value.values())
            for key in ("tags", "hashtags", "source_tags"):
                nested = value.get(key)
                if isinstance(nested, list):
                    nested_values.extend(nested)
                elif nested:
                    nested_values.append(nested)
            text = json.dumps(_json_safe(nested_values), ensure_ascii=False)
        elif isinstance(value, list):
            text = json.dumps(_json_safe(value), ensure_ascii=False)
        else:
            text = str(value)
        for raw_tag in re.findall(r"#[\wА-Яа-яІіЇїЄєҐґ-]+", text, flags=re.UNICODE):
            key = raw_tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(raw_tag)
    return tags


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class MeetingDigestBotClient:
    base_url: str | None = None
    channel_username: str | None = None
    shared_secret: str | None = None
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        self.base_url = _normalize_base_url(self.base_url)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def register_meeting_publication(
        self,
        *,
        meeting: Any,
        telegram_result: dict[str, Any],
        google_result: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"registered": False, "reason": "MeetingDigestBot is disabled."}
        post_url = build_telegram_post_url(
            chat_id=telegram_result.get("chat_id"),
            message_id=telegram_result.get("message_id"),
            channel_username=self.channel_username,
        )
        if not post_url:
            return {"registered": False, "reason": "Telegram message_id/chat_id is missing."}
        source_tags = extract_source_tags(
            getattr(meeting, "title", None),
            getattr(meeting, "meeting_type", None),
            payload or {},
        )
        payload_body = dict(payload or {})
        if source_tags:
            payload_body["source_tags"] = source_tags
        body = {
            "post_url": post_url,
            "telegram_chat_id": str(telegram_result.get("chat_id") or ""),
            "telegram_message_id": str(telegram_result.get("message_id") or ""),
            "digest_type": "meeting",
            "loom_video_id": getattr(meeting, "loom_video_id", None),
            "meeting_title": getattr(meeting, "title", None),
            "source_url": getattr(meeting, "source_url", None),
            "google_doc_url": (google_result or {}).get("google_doc_url"),
            "transcript_doc_url": (google_result or {}).get("transcript_doc_url"),
            "source_tags": source_tags,
            "payload": payload_body,
        }
        return self._register(_json_safe(body))

    def register_daily_publication(
        self,
        *,
        report_date: date,
        telegram_result: dict[str, Any],
        google_doc_url: str | None = None,
        transcript_doc_url: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"registered": False, "reason": "MeetingDigestBot is disabled."}
        post_url = build_telegram_post_url(
            chat_id=telegram_result.get("chat_id"),
            message_id=telegram_result.get("message_id"),
            channel_username=self.channel_username,
        )
        if not post_url:
            return {"registered": False, "reason": "Telegram message_id/chat_id is missing."}
        body = {
            "post_url": post_url,
            "telegram_chat_id": str(telegram_result.get("chat_id") or ""),
            "telegram_message_id": str(telegram_result.get("message_id") or ""),
            "digest_type": "daily",
            "report_date": report_date.isoformat(),
            "google_doc_url": google_doc_url,
            "transcript_doc_url": transcript_doc_url,
            "payload": payload or {},
        }
        return self._register(_json_safe(body))

    def _register(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self.shared_secret:
            headers["X-Meeting-Digest-Secret"] = self.shared_secret
        response = requests.post(
            f"{self.base_url}/publications/register",
            json=body,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        payload["registered"] = True
        return payload

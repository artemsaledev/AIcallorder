from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass
class TelegramNotifier:
    bot_token: str | None = None
    chat_id: str | None = None

    def send_digest(self, text: str) -> dict:
        if not self.bot_token or not self.chat_id:
            return {"sent": False, "reason": "Telegram credentials are not configured."}
        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text[:4000],
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "sent": bool(payload.get("ok")),
            "message_id": payload.get("result", {}).get("message_id"),
            "preview": text[:500],
        }

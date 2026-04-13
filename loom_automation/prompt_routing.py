from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PromptRoute(BaseModel):
    name: str
    title_include_keywords: list[str] = Field(default_factory=list)
    title_exclude_keywords: list[str] = Field(default_factory=list)
    prompt_path: str
    enabled: bool = True

    def matches(self, title: str) -> bool:
        normalized = _normalize_title(title)
        if self.title_include_keywords:
            include_ok = any(_normalize_title(keyword) in normalized for keyword in self.title_include_keywords)
            if not include_ok:
                return False
        if self.title_exclude_keywords:
            exclude_hit = any(_normalize_title(keyword) in normalized for keyword in self.title_exclude_keywords)
            if exclude_hit:
                return False
        return True


class PromptRoutingConfig(BaseModel):
    routes: list[PromptRoute] = Field(default_factory=list)

    def resolve_route(self, title: str) -> PromptRoute | None:
        for route in self.routes:
            if route.enabled and route.matches(title):
                return route
        return None


def load_prompt_routing_config(path: str | None) -> PromptRoutingConfig:
    if not path:
        return PromptRoutingConfig()
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.exists():
        return PromptRoutingConfig()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return PromptRoutingConfig()
    if isinstance(payload, list):
        payload = {"routes": payload}
    if not isinstance(payload, dict):
        return PromptRoutingConfig()
    return PromptRoutingConfig.model_validate(payload)


def load_prompt_text(path: str) -> str:
    prompt_path = Path(path)
    if not prompt_path.is_absolute():
        prompt_path = Path.cwd() / prompt_path
    return prompt_path.read_text(encoding="utf-8-sig").strip()


def title_matches_keywords(title: str, include_keywords: list[str], exclude_keywords: list[str]) -> bool:
    normalized = _normalize_title(title)
    if include_keywords:
        if not any(_normalize_title(keyword) in normalized for keyword in include_keywords):
            return False
    if exclude_keywords:
        if any(_normalize_title(keyword) in normalized for keyword in exclude_keywords):
            return False
    return True


def _normalize_title(value: str) -> str:
    return " ".join(str(value).lower().strip().split())

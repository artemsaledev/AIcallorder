from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
import shlex
import subprocess
from typing import Any

import requests

from loom_automation.models import (
    ActionItem,
    BusinessTask,
    DailyDigestArtifacts,
    MeetingArtifacts,
    TechnicalSpecDraft,
)
from loom_automation.prompts import (
    DAILY_DIGEST_SYSTEM_PROMPT,
    DAILY_DIGEST_USER_TEMPLATE,
    MEETING_ANALYSIS_SYSTEM_PROMPT,
    MEETING_ANALYSIS_USER_TEMPLATE,
)


@dataclass
class Summarizer:
    llm_provider: str = "auto"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"
    local_llm_command: str | None = None
    timeout_seconds: int = 120

    def summarize(
        self,
        transcript_text: str,
        *,
        meeting_title: str = "Loom meeting",
        meeting_type: str = "general",
    ) -> MeetingArtifacts:
        prompt = MEETING_ANALYSIS_USER_TEMPLATE.format(
            meeting_title=meeting_title,
            meeting_type=meeting_type,
            transcript_text=transcript_text[:30000],
        )
        payload = self._invoke_llm(
            system_prompt=MEETING_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        if payload is None:
            return self._fallback_meeting_artifacts(transcript_text, meeting_title=meeting_title)
        return self._parse_meeting_artifacts(payload, transcript_text=transcript_text, meeting_title=meeting_title)

    def summarize_daily(self, report_date: date, items: list[dict[str, Any]]) -> DailyDigestArtifacts:
        prompt = DAILY_DIGEST_USER_TEMPLATE.format(
            report_date=report_date.isoformat(),
            artifacts_json=json.dumps(items, ensure_ascii=False)[:30000],
        )
        payload = self._invoke_llm(
            system_prompt=DAILY_DIGEST_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        if payload is None:
            return self._fallback_daily_digest(report_date, items)
        return self._parse_daily_digest(payload, report_date=report_date, items=items)

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
        if self.openai_api_key:
            return self._invoke_openai(system_prompt=system_prompt, user_prompt=user_prompt)
        return None

    def _invoke_local_llm(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | None:
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
        base_url = (self.openai_base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.openai_model,
                    "temperature": 0.2,
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
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not content:
            return None
        return self._extract_json_object(content)

    def _extract_json_object(self, raw_text: str) -> dict[str, Any] | None:
        text = self._sanitize_llm_output(raw_text)
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

    def _parse_meeting_artifacts(
        self,
        payload: dict[str, Any],
        *,
        transcript_text: str,
        meeting_title: str,
    ) -> MeetingArtifacts:
        summary = self._clean_text(payload.get("summary")) or self._fallback_summary(transcript_text)
        completed_today = self._clean_str_list(payload.get("completed_today"))
        remaining_tech_debt = self._clean_str_list(payload.get("remaining_tech_debt"))
        business_requests = self._parse_business_tasks(payload.get("business_requests_for_estimation"))
        blockers = self._clean_str_list(payload.get("blockers"))
        action_items = self._parse_action_items(payload.get("action_items"))
        return MeetingArtifacts(
            summary=summary,
            decisions=self._clean_str_list(payload.get("decisions")),
            completed_today=completed_today,
            remaining_tech_debt=remaining_tech_debt,
            business_requests_for_estimation=business_requests,
            blockers=blockers,
            action_items=action_items,
            technical_spec_draft=self._parse_technical_spec_draft(
                payload.get("technical_spec_draft"),
                fallback_title=meeting_title,
            ),
            telegram_digest=self._format_meeting_telegram_digest(
                meeting_title=meeting_title,
                summary=summary,
                completed_today=completed_today,
                remaining_tech_debt=remaining_tech_debt,
                business_requests=business_requests,
                blockers=blockers,
                action_items=action_items,
                suggested_digest=self._clean_text(payload.get("telegram_digest")),
            ),
        )

    def _parse_daily_digest(
        self,
        payload: dict[str, Any],
        *,
        report_date: date,
        items: list[dict[str, Any]],
    ) -> DailyDigestArtifacts:
        fallback = self._fallback_daily_digest(report_date, items)
        summary = self._clean_text(payload.get("summary")) or fallback.summary
        completed_today = self._clean_str_list(payload.get("completed_today")) or fallback.completed_today
        remaining_tech_debt = (
            self._clean_str_list(payload.get("remaining_tech_debt")) or fallback.remaining_tech_debt
        )
        business_requests = (
            self._parse_business_tasks(payload.get("business_requests_for_estimation"))
            or fallback.business_requests_for_estimation
        )
        blockers = self._clean_str_list(payload.get("blockers")) or fallback.blockers
        action_items = self._parse_action_items(payload.get("action_items")) or fallback.action_items
        return DailyDigestArtifacts(
            report_date=report_date,
            summary=summary,
            completed_today=completed_today,
            remaining_tech_debt=remaining_tech_debt,
            business_requests_for_estimation=business_requests,
            blockers=blockers,
            action_items=action_items,
            telegram_digest=self._format_daily_telegram_digest_v2(
                report_date=report_date,
                summary=summary,
                completed_today=completed_today,
                remaining_tech_debt=remaining_tech_debt,
                business_requests=business_requests,
                blockers=blockers,
                action_items=action_items,
                items=items,
                suggested_digest=self._clean_text(payload.get("telegram_digest")) or fallback.telegram_digest,
            ),
        )

    def _fallback_meeting_artifacts(self, transcript_text: str, *, meeting_title: str) -> MeetingArtifacts:
        lines = [line.strip() for line in transcript_text.splitlines() if line.strip()]
        summary = self._fallback_summary(transcript_text)
        action_items = []
        for line in lines:
            lowered = line.lower()
            if "todo" in lowered or "need to" in lowered or "нужно" in lowered:
                action_items.append(ActionItem(title=line))

        tech_debt = [line for line in lines if "tech debt" in line.lower() or "техдолг" in line.lower()]
        completed = [line for line in lines if "done" in line.lower() or "выполн" in line.lower()]
        blockers = [line for line in lines if "blocker" in line.lower() or "блокер" in line.lower()]
        return MeetingArtifacts(
            summary=summary,
            decisions=[],
            completed_today=completed[:8],
            remaining_tech_debt=tech_debt[:8],
            business_requests_for_estimation=[],
            blockers=blockers[:8],
            action_items=action_items[:10],
            technical_spec_draft=TechnicalSpecDraft(
                title=f"Draft spec: {meeting_title}",
                goal="Promote the discussed changes into an implementable technical task.",
                business_context=summary,
            ),
            telegram_digest=summary,
        )

    def _fallback_daily_digest(self, report_date: date, items: list[dict[str, Any]]) -> DailyDigestArtifacts:
        completed: list[str] = []
        tech_debt: list[str] = []
        blockers: list[str] = []
        action_items: list[ActionItem] = []
        business_tasks: list[BusinessTask] = []
        titles: list[str] = []

        for item in items:
            title = str(item.get("title", "")).strip()
            artifacts = item.get("artifacts", {}) or {}
            if title:
                titles.append(title)
            completed.extend(self._clean_str_list(artifacts.get("completed_today")))
            tech_debt.extend(self._clean_str_list(artifacts.get("remaining_tech_debt")))
            blockers.extend(self._clean_str_list(artifacts.get("blockers")))
            action_items.extend(self._parse_action_items(artifacts.get("action_items")))
            business_tasks.extend(self._parse_business_tasks(artifacts.get("business_requests_for_estimation")))

        summary = (
            f"За {report_date.isoformat()} обработано встреч: {len(items)}."
            if items
            else f"За {report_date.isoformat()} встреч с артефактами не найдено."
        )

        return DailyDigestArtifacts(
            report_date=report_date,
            summary=summary,
            completed_today=completed[:12],
            remaining_tech_debt=tech_debt[:12],
            business_requests_for_estimation=business_tasks[:12],
            blockers=blockers[:12],
            action_items=action_items[:12],
            telegram_digest=self._format_daily_telegram_digest_v2(
                report_date=report_date,
                summary=summary,
                completed_today=completed[:12],
                remaining_tech_debt=tech_debt[:12],
                business_requests=business_tasks[:12],
                blockers=blockers[:12],
                action_items=action_items[:12],
                items=items,
                suggested_digest="",
            ),
        )

    def _fallback_summary(self, transcript_text: str) -> str:
        lines = [line.strip() for line in transcript_text.splitlines() if line.strip()]
        return " ".join(lines[:6])[:1200] or "Summary pending."

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if "\\u" in text:
            try:
                text = text.encode("utf-8").decode("unicode_escape")
            except Exception:
                pass
        return re.sub(r"\s+", " ", text).strip()

    def _clean_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = self._clean_text(item)
            if text:
                result.append(text)
        return result

    def _parse_action_items(self, value: Any) -> list[ActionItem]:
        if not isinstance(value, list):
            return []
        result: list[ActionItem] = []
        for item in value:
            if not isinstance(item, dict):
                text = self._clean_text(item)
                if text:
                    result.append(ActionItem(title=text))
                continue
            title = self._clean_text(item.get("title"))
            if not title:
                continue
            result.append(
                ActionItem(
                    title=title,
                    owner=self._clean_text(item.get("owner")) or None,
                    due_date=self._parse_due_date(item.get("due_date")),
                    status=self._clean_text(item.get("status")) or "open",
                )
            )
        return result

    def _parse_business_tasks(self, value: Any) -> list[BusinessTask]:
        if not isinstance(value, list):
            return []
        result: list[BusinessTask] = []
        for item in value:
            if not isinstance(item, dict):
                text = self._clean_text(item)
                if text:
                    result.append(BusinessTask(title=text))
                continue
            title = self._clean_text(item.get("title"))
            if not title:
                continue
            result.append(
                BusinessTask(
                    title=title,
                    context=self._clean_text(item.get("context")),
                    requested_by=self._clean_text(item.get("requested_by")) or None,
                    priority=self._clean_text(item.get("priority")) or "unknown",
                    estimate_notes=self._clean_text(item.get("estimate_notes")),
                )
            )
        return result

    def _parse_technical_spec_draft(self, value: Any, *, fallback_title: str) -> TechnicalSpecDraft:
        if not isinstance(value, dict):
            return TechnicalSpecDraft(title=f"Draft spec: {fallback_title}")
        return TechnicalSpecDraft(
            title=self._clean_text(value.get("title")) or f"Draft spec: {fallback_title}",
            goal=self._clean_text(value.get("goal")),
            business_context=self._clean_text(value.get("business_context")),
            scope=self._clean_str_list(value.get("scope")),
            functional_requirements=self._clean_str_list(value.get("functional_requirements")),
            non_functional_requirements=self._clean_str_list(value.get("non_functional_requirements")),
            dependencies=self._clean_str_list(value.get("dependencies")),
            acceptance_criteria=self._clean_str_list(value.get("acceptance_criteria")),
            open_questions=self._clean_str_list(value.get("open_questions")),
        )

    def _parse_due_date(self, value: Any) -> date | None:
        text = self._clean_text(value)
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except Exception:
            return None

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

    def _sanitize_llm_output(self, raw_text: str) -> str:
        text = raw_text or ""
        text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
        text = text.replace("```json", "").replace("```", "")
        return text.strip()

    def _format_meeting_telegram_digest(
        self,
        *,
        meeting_title: str,
        summary: str,
        completed_today: list[str],
        remaining_tech_debt: list[str],
        business_requests: list[BusinessTask],
        blockers: list[str],
        action_items: list[ActionItem],
        suggested_digest: str,
    ) -> str:
        lines = [f"Встреча: {meeting_title}"]
        clean_summary = self._trim_line(summary, 240)
        if clean_summary:
            lines.append(f"Итог: {clean_summary}")
        if completed_today:
            lines.append("Сделано: " + "; ".join(self._trim_items(completed_today, 2, 90)))
        if remaining_tech_debt:
            lines.append("Техдолг: " + "; ".join(self._trim_items(remaining_tech_debt, 2, 90)))
        if business_requests:
            lines.append(
                "На оценку: "
                + "; ".join(self._trim_line(item.title, 90) for item in business_requests[:2] if item.title)
            )
        if blockers:
            lines.append("Блокеры: " + "; ".join(self._trim_items(blockers, 2, 90)))
        if action_items:
            lines.append("Следующий шаг: " + "; ".join(self._trim_line(item.title, 90) for item in action_items[:2]))

        digest = "\n".join(line for line in lines if line.strip())
        if len(digest) < 80 and suggested_digest:
            digest = suggested_digest
        return self._trim_line(self._strip_timestamps(digest), 1200, preserve_newlines=True)

    def _format_daily_telegram_digest(
        self,
        *,
        report_date: date,
        summary: str,
        completed_today: list[str],
        remaining_tech_debt: list[str],
        business_requests: list[BusinessTask],
        blockers: list[str],
        action_items: list[ActionItem],
        items: list[dict[str, Any]],
        suggested_digest: str,
    ) -> str:
        meeting_titles = []
        for item in items:
            title = self._clean_text(item.get("title"))
            if title:
                meeting_titles.append(title)
        meeting_titles = self._dedupe_preserve(meeting_titles)

        lines = [f"Daily digest за {report_date.isoformat()}"]
        if summary:
            lines.append("Итог дня: " + self._trim_line(summary, 220))
        if meeting_titles:
            title_preview = ", ".join(self._trim_line(title, 55) for title in meeting_titles[:3])
            tail = f" и еще {len(meeting_titles) - 3}" if len(meeting_titles) > 3 else ""
            lines.append(f"Встречи: {title_preview}{tail}")
        if completed_today:
            lines.append("Сделано: " + "; ".join(self._trim_items(completed_today, 3, 85)))
        if remaining_tech_debt:
            lines.append("Техдолг: " + "; ".join(self._trim_items(remaining_tech_debt, 3, 85)))
        if business_requests:
            lines.append(
                "На оценку: "
                + "; ".join(self._trim_line(item.title, 85) for item in business_requests[:3] if item.title)
            )
        if blockers:
            lines.append("Блокеры: " + "; ".join(self._trim_items(blockers, 2, 85)))
        if action_items:
            lines.append(
                "Фокус дальше: "
                + "; ".join(self._trim_line(item.title, 85) for item in action_items[:3] if item.title)
            )

        digest = "\n".join(line for line in lines if line.strip())
        if len(digest) < 120 and suggested_digest:
            digest = suggested_digest
        digest = self._strip_timestamps(digest)
        return self._trim_line(digest, 1800, preserve_newlines=True)

    def _trim_items(self, values: list[str], limit: int, max_len: int) -> list[str]:
        cleaned = []
        for value in self._dedupe_preserve(values):
            text = self._trim_line(value, max_len)
            if text:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _dedupe_preserve(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = self._clean_text(self._strip_timestamps(value)).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(self._clean_text(self._strip_timestamps(value)))
        return result

    def _strip_timestamps(self, text: str) -> str:
        cleaned_lines = []
        for line in str(text).splitlines():
            line = re.sub(r"(?:^|\s)\d{1,2}:\d{2}(?::\d{2})?\s*", " ", line)
            line = re.sub(r"\s+", " ", line).strip(" -")
            if line:
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    def _trim_line(self, text: str, max_len: int, preserve_newlines: bool = False) -> str:
        value = self._clean_text(text)
        if preserve_newlines:
            value = "\n".join(self._clean_text(line) for line in str(text).splitlines() if self._clean_text(line))
        value = self._strip_timestamps(value)
        if len(value) <= max_len:
            return value
        shortened = value[: max_len - 1].rstrip(" ,;:.")
        return shortened + "…"

    def _format_daily_telegram_digest_v2(
        self,
        *,
        report_date: date,
        summary: str,
        completed_today: list[str],
        remaining_tech_debt: list[str],
        business_requests: list[BusinessTask],
        blockers: list[str],
        action_items: list[ActionItem],
        items: list[dict[str, Any]],
        suggested_digest: str,
    ) -> str:
        meeting_titles = []
        for item in items:
            title = self._clean_text(item.get("title"))
            if title:
                meeting_titles.append(title)
        meeting_titles = self._dedupe_preserve(meeting_titles)

        lines = [f"Daily digest за {report_date.isoformat()}"]
        if summary:
            lines.extend(["", "Итог дня", f"  {self._trim_to_sentence_v2(summary, 700)}"])
        if meeting_titles:
            lines.extend(["", "Встречи"])
            for title in meeting_titles[:8]:
                lines.append(f"  - {self._trim_to_sentence_v2(title, 120)}")
            if len(meeting_titles) > 8:
                lines.append(f"  - Еще встреч: {len(meeting_titles) - 8}.")
        if completed_today:
            lines.extend(["", "Сделано"])
            lines.extend(self._render_daily_block_items_v2(completed_today, limit=8, max_len=220))
        if remaining_tech_debt:
            lines.extend(["", "Техдолг"])
            lines.extend(self._render_daily_block_items_v2(remaining_tech_debt, limit=8, max_len=220))
        if business_requests:
            lines.extend(["", "На оценку"])
            for item in business_requests[:8]:
                text = self._compose_business_task_line_v2(item, max_len=260)
                if text:
                    lines.append(f"  - {text}")
        if blockers:
            lines.extend(["", "Блокеры"])
            lines.extend(self._render_daily_block_items_v2(blockers, limit=6, max_len=220))
        if action_items:
            lines.extend(["", "Фокус дальше"])
            for item in action_items[:8]:
                text = self._compose_action_item_line_v2(item, max_len=260)
                if text:
                    lines.append(f"  - {text}")

        digest = "\n".join(line for line in lines if line.strip())
        if len(digest) < 120 and suggested_digest:
            digest = self._trim_to_sentence_v2(suggested_digest, 3200)
        digest = self._strip_timestamps(digest)
        return self._trim_multiline_message_v2(digest, 3200)

    def _trim_to_sentence_v2(self, text: str, max_len: int) -> str:
        value = self._strip_timestamps(self._clean_text(text))
        if len(value) <= max_len:
            return value
        cutoff = value[:max_len].rstrip()
        sentence_end = max(cutoff.rfind(". "), cutoff.rfind("! "), cutoff.rfind("? "))
        if sentence_end >= int(max_len * 0.55):
            return cutoff[: sentence_end + 1].rstrip()
        clause_end = max(cutoff.rfind("; "), cutoff.rfind(": "))
        if clause_end >= int(max_len * 0.65):
            return cutoff[: clause_end + 1].rstrip()
        return cutoff.rstrip(" ,;:.")

    def _trim_multiline_message_v2(self, text: str, max_len: int) -> str:
        normalized_lines = [line.rstrip() for line in str(text).splitlines()]
        result: list[str] = []
        current_length = 0
        for line in normalized_lines:
            addition = line if not result else "\n" + line
            if current_length + len(addition) > max_len:
                break
            result.append(line)
            current_length += len(addition)
        return "\n".join(result).strip()

    def _render_daily_block_items_v2(self, values: list[str], *, limit: int, max_len: int) -> list[str]:
        lines: list[str] = []
        for value in self._dedupe_preserve(values):
            text = self._trim_to_sentence_v2(value, max_len)
            if text:
                lines.append(f"  - {text}")
            if len(lines) >= limit:
                break
        return lines

    def _compose_business_task_line_v2(self, item: BusinessTask, *, max_len: int) -> str:
        parts = [item.title]
        if item.priority and item.priority != "unknown":
            parts.append(f"приоритет: {item.priority}")
        if item.requested_by:
            parts.append(f"инициатор: {item.requested_by}")
        if item.context:
            parts.append(f"контекст: {item.context}")
        if item.estimate_notes:
            parts.append(f"оценка: {item.estimate_notes}")
        return self._trim_to_sentence_v2(". ".join(part for part in parts if part), max_len)

    def _compose_action_item_line_v2(self, item: ActionItem, *, max_len: int) -> str:
        parts = [item.title]
        if item.owner:
            parts.append(f"owner: {item.owner}")
        if item.due_date:
            parts.append(f"due: {item.due_date}")
        if item.status:
            parts.append(f"status: {item.status}")
        return self._trim_to_sentence_v2(". ".join(part for part in parts if part), max_len)

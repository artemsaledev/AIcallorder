from __future__ import annotations

from dataclasses import dataclass

from loom_automation.models import MeetingArtifacts, MeetingMetadata


@dataclass
class TelegramReporter:
    """Formats operational Telegram messages for the team."""

    def render_meeting_digest(self, meeting: MeetingMetadata, artifacts: MeetingArtifacts) -> str:
        lines = [
            f"Meeting: {meeting.title}",
            "",
            "Summary",
            artifacts.summary,
        ]
        if artifacts.completed_today:
            lines.extend(["", "Done", *[f"- {item}" for item in artifacts.completed_today[:5]]])
        if artifacts.action_items:
            lines.extend(
                [
                    "",
                    "Action items",
                    *[
                        f"- {item.title} | owner={item.owner or '-'} | due={item.due_date or '-'} | status={item.status}"
                        for item in artifacts.action_items[:5]
                    ],
                ]
            )
        if artifacts.remaining_tech_debt:
            lines.extend(["", "Tech debt", *[f"- {item}" for item in artifacts.remaining_tech_debt[:5]]])
        if artifacts.business_requests_for_estimation:
            lines.extend(
                [
                    "",
                    "For estimation",
                    *[f"- {item.title}" for item in artifacts.business_requests_for_estimation[:5]],
                ]
            )
        if artifacts.blockers:
            lines.extend(["", "Blockers", *[f"- {item}" for item in artifacts.blockers[:5]]])
        lines.extend(["", f"Loom: {meeting.source_url}"])
        return "\n".join(lines)

    def render_daily_digest(self, items: list[dict]) -> str:
        lines = ["Daily team digest"]
        for item in items:
            title = item.get("title", "Untitled")
            summary = item.get("artifacts", {}).get("summary", "No summary")
            lines.append(f"- {title}: {summary}")
        return "\n".join(lines)

    def append_meeting_links(
        self,
        text: str,
        *,
        meeting: MeetingMetadata,
        google_doc_url: str | None = None,
        doc_section_title: str | None = None,
        transcript_doc_url: str | None = None,
        transcript_section_title: str | None = None,
    ) -> str:
        lines = [text.rstrip()]
        lines.extend(
            [
                "",
                "Links",
                f"Loom: {meeting.source_url}",
            ]
        )
        if google_doc_url:
            lines.append(f"Google Doc: {google_doc_url}")
        if doc_section_title:
            lines.append(f"Doc section: {doc_section_title}")
        if transcript_doc_url:
            lines.append(f"Transcript Doc: {transcript_doc_url}")
        if transcript_section_title:
            lines.append(f"Transcript section: {transcript_section_title}")
        return "\n".join(line for line in lines if line is not None).strip()

    def append_daily_links(
        self,
        text: str,
        *,
        items: list[dict],
        google_doc_url: str | None = None,
        transcript_doc_url: str | None = None,
    ) -> str:
        lines = [text.rstrip()]
        if google_doc_url:
            lines.extend(["", f"Google Doc: {google_doc_url}"])
        if transcript_doc_url:
            lines.append(f"Transcript Doc: {transcript_doc_url}")
        if items:
            lines.extend(["", "Meeting links"])
            for item in items[:8]:
                title = item.get("title", "Untitled")
                source_url = item.get("source_url", "")
                transcript_section_title = item.get("transcript_section_title", f"Transcript: {title}")
                lines.append(f"- {title}")
                if source_url:
                    lines.append(f"  Loom: {source_url}")
                if google_doc_url:
                    lines.append(f"  Doc section: Meeting Note: {title}")
                if transcript_doc_url:
                    lines.append(f"  Transcript section: {transcript_section_title}")
        return "\n".join(line for line in lines if line is not None).strip()

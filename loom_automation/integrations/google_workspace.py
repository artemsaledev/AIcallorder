from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from loom_automation.models import MeetingArtifacts, MeetingMetadata


DOC_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@dataclass
class GoogleWorkspacePublisher:
    service_account_json: str | None = None
    docs_folder_id: str | None = None
    doc_id: str | None = None
    sheets_id: str | None = None
    worksheet_name: str = "Transcript"

    def current_doc_url(self) -> str | None:
        if self.doc_id:
            return f"https://docs.google.com/document/d/{self.doc_id}/edit"
        return None

    def section_title(self, meeting: MeetingMetadata) -> str:
        return f"Meeting Note: {meeting.title}"

    def publish_meeting_artifacts(self, meeting: MeetingMetadata, artifacts: MeetingArtifacts) -> dict:
        if not self.service_account_json:
            return self._result(note="GOOGLE_SERVICE_ACCOUNT_JSON is not configured.")

        service_account_path = Path(self.service_account_json)
        if not service_account_path.exists():
            return self._result(note=f"Service account JSON not found: {service_account_path}")

        result = self._result(note="Google publication completed.")
        doc_url = self._upsert_google_doc(meeting, artifacts)
        if doc_url:
            result["google_doc_url"] = doc_url

        sheet_row = self._upsert_google_sheet_row(meeting, artifacts, doc_url)
        if sheet_row is not None:
            result["google_sheet_row"] = sheet_row

        if not doc_url and sheet_row is None:
            result["note"] = (
                "Google credentials are available, but neither Docs nor Sheets target is fully configured. "
                "Set GOOGLE_DOCS_FOLDER_ID and/or GOOGLE_SHEETS_ID."
            )
        elif isinstance(doc_url, str) and doc_url.startswith("google-doc-error:") and sheet_row is not None:
            result["note"] = (
                f"Google Sheets updated, but Google Docs access failed with {doc_url}. "
                "Share the target Google Doc or folder with the service account as Editor."
            )
        elif not doc_url:
            result["note"] = "Google Sheets updated. GOOGLE_DOCS_FOLDER_ID or GOOGLE_DOC_ID is not configured."
        elif sheet_row is None:
            result["note"] = "Google Doc updated. GOOGLE_SHEETS_ID is not configured."

        return result

    def _upsert_google_doc(self, meeting: MeetingMetadata, artifacts: MeetingArtifacts) -> str | None:
        if not self.docs_folder_id and not self.doc_id:
            return None

        creds = Credentials.from_service_account_file(str(self.service_account_json), scopes=DOC_SCOPES)
        docs = build("docs", "v1", credentials=creds, cache_discovery=False)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)

        title = self._doc_title(meeting)
        body_text = self._render_doc_text(meeting, artifacts)

        try:
            if self.doc_id:
                self._upsert_master_doc_section(docs, self.doc_id, meeting, artifacts)
                file_id = self.doc_id
            else:
                file_id = self._find_existing_doc_id(drive, title, self.docs_folder_id)
                if not file_id:
                    created = docs.documents().create(body={"title": title}).execute()
                    file_id = created["documentId"]
                    drive.files().update(
                        fileId=file_id,
                        addParents=self.docs_folder_id,
                        removeParents="root",
                        fields="id, parents",
                    ).execute()

                doc = docs.documents().get(documentId=file_id).execute()
                end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
                requests = []
                if end_index > 1:
                    requests.append(
                        {
                            "deleteContentRange": {
                                "range": {
                                    "startIndex": 1,
                                    "endIndex": end_index - 1,
                                }
                            }
                        }
                    )
                requests.append({"insertText": {"location": {"index": 1}, "text": body_text}})
                docs.documents().batchUpdate(documentId=file_id, body={"requests": requests}).execute()
        except HttpError as exc:
            return f"google-doc-error:{exc.status_code}"

        return f"https://docs.google.com/document/d/{file_id}/edit"

    def _upsert_master_doc_section(self, docs, doc_id: str, meeting: MeetingMetadata, artifacts: MeetingArtifacts) -> None:
        marker_start = f"[[LOOM_VIDEO_ID:{meeting.loom_video_id}]]"
        marker_end = f"[[/LOOM_VIDEO_ID:{meeting.loom_video_id}]]"
        section_text = (
            f"{marker_start}\n"
            f"{self._render_doc_text(meeting, artifacts)}"
            f"{marker_end}\n\n"
        )
        doc = docs.documents().get(documentId=doc_id).execute()
        start_range = self._find_text_range(doc, marker_start)
        end_range = self._find_text_range(doc, marker_end)
        requests = []
        if start_range and end_range:
            requests.append(
                {
                    "deleteContentRange": {
                        "range": {
                            "startIndex": start_range[0],
                            "endIndex": end_range[1],
                        }
                    }
                }
            )
            requests.append({"insertText": {"location": {"index": start_range[0]}, "text": section_text}})
        else:
            end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
            insert_index = max(1, end_index - 1)
            requests.append({"insertText": {"location": {"index": insert_index}, "text": section_text}})
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    def _upsert_google_sheet_row(
        self,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        doc_url: str | None,
    ) -> int | None:
        if not self.sheets_id:
            return None

        creds = Credentials.from_service_account_file(str(self.service_account_json), scopes=SHEET_SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(self.sheets_id)
        worksheet = self._get_or_create_worksheet(sheet)
        headers = self._ensure_sheet_headers(worksheet)
        row_values = self._build_sheet_row(meeting, artifacts, doc_url, headers)

        loom_video_column = headers.index("loom_video_id") + 1
        matches = worksheet.findall(meeting.loom_video_id, in_column=loom_video_column)
        if matches:
            row_index = matches[0].row
            worksheet.update(f"A{row_index}:{self._column_letter(len(headers))}{row_index}", [row_values])
            return row_index

        worksheet.append_row(row_values, value_input_option="USER_ENTERED")
        matches = worksheet.findall(meeting.loom_video_id, in_column=loom_video_column)
        return matches[0].row if matches else None

    def _get_or_create_worksheet(self, sheet):
        try:
            return sheet.worksheet(self.worksheet_name)
        except gspread.WorksheetNotFound:
            return sheet.add_worksheet(title=self.worksheet_name, rows=1000, cols=20)

    def _ensure_sheet_headers(self, worksheet) -> list[str]:
        headers = worksheet.row_values(1)
        expected = [
            "loom_video_id",
            "title",
            "meeting_type",
            "recorded_at",
            "source_url",
            "summary",
            "decisions",
            "completed_today",
            "remaining_tech_debt",
            "business_requests_for_estimation",
            "blockers",
            "action_items",
            "technical_spec_title",
            "technical_spec_goal",
            "telegram_digest",
            "google_doc_url",
            "updated_at",
        ]
        if headers != expected:
            worksheet.update("A1:Q1", [expected])
            return expected
        return headers

    def _build_sheet_row(
        self,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        doc_url: str | None,
        headers: list[str],
    ) -> list[str]:
        values = {
            "loom_video_id": meeting.loom_video_id,
            "title": meeting.title,
            "meeting_type": meeting.meeting_type,
            "recorded_at": meeting.recorded_at.isoformat() if meeting.recorded_at else "",
            "source_url": meeting.source_url,
            "summary": artifacts.summary,
            "decisions": self._json_dump(artifacts.decisions),
            "completed_today": self._json_dump(artifacts.completed_today),
            "remaining_tech_debt": self._json_dump(artifacts.remaining_tech_debt),
            "business_requests_for_estimation": self._json_dump(
                [item.model_dump() for item in artifacts.business_requests_for_estimation]
            ),
            "blockers": self._json_dump(artifacts.blockers),
            "action_items": self._json_dump([item.model_dump(mode="json") for item in artifacts.action_items]),
            "technical_spec_title": artifacts.technical_spec_draft.title,
            "technical_spec_goal": artifacts.technical_spec_draft.goal,
            "telegram_digest": artifacts.telegram_digest,
            "google_doc_url": doc_url or "",
            "updated_at": datetime.utcnow().isoformat(),
        }
        return [values.get(header, "") for header in headers]

    def _find_existing_doc_id(self, drive, title: str, folder_id: str) -> str | None:
        safe_title = title.replace("'", "\\'")
        query = (
            "mimeType = 'application/vnd.google-apps.document' "
            f"and name = '{safe_title}' "
            f"and '{folder_id}' in parents and trashed = false"
        )
        response = drive.files().list(q=query, fields="files(id, name)", pageSize=1).execute()
        files = response.get("files", [])
        return files[0]["id"] if files else None

    def _doc_title(self, meeting: MeetingMetadata) -> str:
        return f"AIcallorder - {meeting.title} - {meeting.loom_video_id}"

    def _find_text_range(self, doc: dict, needle: str) -> tuple[int, int] | None:
        full_text = ""
        index_map: list[int] = []
        for element in doc.get("body", {}).get("content", []):
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for item in paragraph.get("elements", []):
                text_run = item.get("textRun")
                if not text_run:
                    continue
                content = text_run.get("content", "")
                start_index = item.get("startIndex", 1)
                for offset, char in enumerate(content):
                    full_text += char
                    index_map.append(start_index + offset)
        pos = full_text.find(needle)
        if pos == -1:
            return None
        start = index_map[pos]
        end = index_map[pos + len(needle) - 1] + 1
        return start, end

    def _render_doc_text(self, meeting: MeetingMetadata, artifacts: MeetingArtifacts) -> str:
        business_requests = [
            (
                f"{item.title}\n"
                f"  Priority: {item.priority}\n"
                f"  Requested by: {item.requested_by or '-'}\n"
                f"  Context: {item.context or '-'}\n"
                f"  Estimate notes: {item.estimate_notes or '-'}"
            )
            for item in artifacts.business_requests_for_estimation
        ]
        action_items = [
            (
                f"{item.title}\n"
                f"  Owner: {item.owner or '-'}\n"
                f"  Due: {item.due_date or '-'}\n"
                f"  Status: {item.status}"
            )
            for item in artifacts.action_items
        ]
        lines = [
            f"Meeting Note: {meeting.title}",
            "",
            "Metadata",
            f"- Loom video ID: {meeting.loom_video_id}",
            f"- Meeting type: {meeting.meeting_type}",
            f"- Recorded at: {meeting.recorded_at.isoformat() if meeting.recorded_at else '-'}",
            f"- Source URL: {meeting.source_url}",
            "",
            "Summary",
            artifacts.summary,
            "",
            "Decisions",
            *self._render_bullets(artifacts.decisions),
            "",
            "Completed Today",
            *self._render_bullets(artifacts.completed_today),
            "",
            "Action Items",
            *self._render_bullets(action_items),
            "",
            "Remaining Tech Debt",
            *self._render_bullets(artifacts.remaining_tech_debt),
            "",
            "Business Requests For Estimation",
            *self._render_bullets(business_requests),
            "",
            "Blockers",
            *self._render_bullets(artifacts.blockers),
            "",
            "Technical Spec Draft",
            f"Title: {artifacts.technical_spec_draft.title or '-'}",
            f"Goal: {artifacts.technical_spec_draft.goal or '-'}",
            f"Business Context: {artifacts.technical_spec_draft.business_context or '-'}",
            "",
            "Scope",
            *self._render_bullets(artifacts.technical_spec_draft.scope),
            "",
            "Functional Requirements",
            *self._render_bullets(artifacts.technical_spec_draft.functional_requirements),
            "",
            "Non-Functional Requirements",
            *self._render_bullets(artifacts.technical_spec_draft.non_functional_requirements),
            "",
            "Dependencies",
            *self._render_bullets(artifacts.technical_spec_draft.dependencies),
            "",
            "Acceptance Criteria",
            *self._render_bullets(artifacts.technical_spec_draft.acceptance_criteria),
            "",
            "Open Questions",
            *self._render_bullets(artifacts.technical_spec_draft.open_questions),
            "",
            "Telegram Digest",
            artifacts.telegram_digest,
            "",
        ]
        return "\n".join(lines)

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["-"]
        return [f"- {item}" for item in items]

    def _json_dump(self, value) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _column_letter(self, index: int) -> str:
        letters = ""
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            letters = chr(65 + remainder) + letters
        return letters

    def _result(self, note: str) -> dict:
        return {
            "google_doc_url": None,
            "google_sheet_row": None,
            "note": note,
        }

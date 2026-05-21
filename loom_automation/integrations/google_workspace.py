from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
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

logger = logging.getLogger(__name__)
DOCS_INSERT_CHUNK_SIZE = 80_000


@dataclass
class GoogleWorkspacePublisher:
    auth_mode: str = "service_account"
    service_account_json: str | None = None
    oauth_client_json: str | None = None
    oauth_token_json: str | None = None
    docs_folder_id: str | None = None
    doc_id: str | None = None
    transcript_doc_id: str | None = None
    transcript_doc_rotate_enabled: bool = True
    transcript_doc_soft_char_limit: int = 900_000
    transcript_doc_state_path: str | None = "data/google_transcript_doc_state.json"
    transcript_doc_title_prefix: str = "LLM-Transcript"
    sheets_id: str | None = None
    worksheet_name: str = "Transcript"

    def current_doc_url(self) -> str | None:
        if self.doc_id:
            return f"https://docs.google.com/document/d/{self.doc_id}/edit"
        return None

    def current_transcript_doc_url(self) -> str | None:
        doc_id = self._active_transcript_doc_id()
        if doc_id:
            return f"https://docs.google.com/document/d/{doc_id}/edit"
        return None

    def section_title(self, meeting: MeetingMetadata) -> str:
        return f"Meeting Note: {meeting.title}"

    def transcript_section_title(self, meeting: MeetingMetadata) -> str:
        return f"Transcript: {meeting.title}"

    def publish_meeting_artifacts(
        self,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        transcript_text: str,
    ) -> dict:
        credentials_note = self._credentials_configuration_note()
        if credentials_note:
            return self._result(note=credentials_note)

        result = self._result(note="Google publication completed.")
        transcript_doc_url = self._upsert_transcript_doc(meeting, transcript_text)
        if transcript_doc_url:
            result["transcript_doc_url"] = transcript_doc_url

        doc_url = self._upsert_google_doc(meeting, artifacts, transcript_doc_url)
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

    def _upsert_google_doc(
        self,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        transcript_doc_url: str | None = None,
    ) -> str | None:
        if not self.docs_folder_id and not self.doc_id:
            return None

        creds = self._credentials(DOC_SCOPES)
        docs = build("docs", "v1", credentials=creds, cache_discovery=False)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)

        title = self._doc_title(meeting)
        body_text = self._render_doc_text(meeting, artifacts, transcript_doc_url=transcript_doc_url)

        try:
            if self.doc_id:
                self._upsert_master_doc_section(
                    docs,
                    self.doc_id,
                    meeting,
                    artifacts,
                    transcript_doc_url=transcript_doc_url,
                )
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
            return self._google_error_label("google-doc-error", exc)

        return f"https://docs.google.com/document/d/{file_id}/edit"

    def _upsert_master_doc_section(
        self,
        docs,
        doc_id: str,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        transcript_doc_url: str | None = None,
    ) -> None:
        marker_start = f"[[LOOM_VIDEO_ID:{meeting.loom_video_id}]]"
        marker_end = f"[[/LOOM_VIDEO_ID:{meeting.loom_video_id}]]"
        section_text = (
            f"{marker_start}\n"
            f"{self._render_doc_text(meeting, artifacts, transcript_doc_url=transcript_doc_url)}"
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
            self._execute_requests(docs, doc_id, requests)
            self._insert_text_chunked(docs, doc_id, start_range[0], section_text)
            return
        else:
            end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
            insert_index = max(1, end_index - 1)
            self._insert_text_chunked(docs, doc_id, insert_index, section_text)
            return
        self._execute_requests(docs, doc_id, requests)

    def _upsert_transcript_doc(self, meeting: MeetingMetadata, transcript_text: str) -> str | None:
        active_doc_id = self._active_transcript_doc_id()
        if not active_doc_id:
            return None

        creds = self._credentials(DOC_SCOPES)
        docs = build("docs", "v1", credentials=creds, cache_discovery=False)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)

        section_title = self.transcript_section_title(meeting)
        marker_start = f"[[TRANSCRIPT_LOOM_VIDEO_ID:{meeting.loom_video_id}]]"
        marker_end = f"[[/TRANSCRIPT_LOOM_VIDEO_ID:{meeting.loom_video_id}]]"
        transcript_section = (
            f"{marker_start}\n"
            f"{section_title}\n\n"
            f"Metadata\n"
            f"- Loom video ID: {meeting.loom_video_id}\n"
            f"- Recorded at: {meeting.recorded_at.isoformat() if meeting.recorded_at else '-'}\n"
            f"- Source URL: {meeting.source_url}\n\n"
            f"Transcript\n"
            f"{transcript_text.strip()}\n"
            f"{marker_end}\n\n"
        )

        try:
            doc = docs.documents().get(documentId=active_doc_id).execute()
            start_range = self._find_text_range(doc, marker_start)
            end_range = self._find_text_range(doc, marker_end)
            if start_range and end_range:
                self._execute_requests(
                    docs,
                    active_doc_id,
                    [
                        {
                            "deleteContentRange": {
                                "range": {
                                    "startIndex": start_range[0],
                                    "endIndex": end_range[1],
                                }
                            }
                        }
                    ],
                )
                self._insert_text_chunked(docs, active_doc_id, start_range[0], transcript_section)
            else:
                end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
                if self._should_rotate_transcript_doc(end_index, transcript_section):
                    active_doc_id = self._create_rotated_transcript_doc(docs, drive, meeting)
                    doc = docs.documents().get(documentId=active_doc_id).execute()
                    end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
                insert_index = max(1, end_index - 1)
                self._insert_text_chunked(docs, active_doc_id, insert_index, transcript_section)
        except HttpError as exc:
            return self._google_error_label("google-transcript-doc-error", exc)

        return self.current_transcript_doc_url()

    def _active_transcript_doc_id(self) -> str | None:
        state = self._load_transcript_doc_state()
        doc_id = state.get("current_doc_id")
        return doc_id or self.transcript_doc_id

    def _load_transcript_doc_state(self) -> dict:
        if not self.transcript_doc_state_path:
            return {}
        state_path = Path(self.transcript_doc_state_path)
        if not state_path.exists():
            return {}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read transcript doc state from %s", state_path)
            return {}

    def _save_transcript_doc_state(self, doc_id: str, title: str) -> None:
        self.transcript_doc_id = doc_id
        if not self.transcript_doc_state_path:
            return
        state_path = Path(self.transcript_doc_state_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_doc_id": doc_id,
            "current_doc_url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "title": title,
            "rotated_at": datetime.utcnow().isoformat(),
        }
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _should_rotate_transcript_doc(self, current_end_index: int, new_text: str) -> bool:
        if not self.transcript_doc_rotate_enabled:
            return False
        if not self.docs_folder_id:
            return False
        return current_end_index + len(new_text) >= self.transcript_doc_soft_char_limit

    def _create_rotated_transcript_doc(self, docs, drive, meeting: MeetingMetadata) -> str:
        suffix = datetime.utcnow().strftime("%Y-%m-%d %H-%M")
        title = f"{self.transcript_doc_title_prefix} {suffix}"
        if self.docs_folder_id:
            created = drive.files().create(
                body={
                    "name": title,
                    "mimeType": "application/vnd.google-apps.document",
                    "parents": [self.docs_folder_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
            file_id = created["id"]
        else:
            created = docs.documents().create(body={"title": title}).execute()
            file_id = created["documentId"]
        try:
            drive.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
                supportsAllDrives=True,
            ).execute()
        except HttpError as exc:
            logger.warning("Could not make rotated transcript doc public for Loom %s: %s", meeting.loom_video_id, exc)
        self._save_transcript_doc_state(file_id, title)
        logger.info("Created rotated transcript doc %s for Loom %s", file_id, meeting.loom_video_id)
        return file_id

    def _execute_requests(self, docs, doc_id: str, requests: list[dict]) -> None:
        if not requests:
            return
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    def _insert_text_chunked(self, docs, doc_id: str, index: int, text: str) -> None:
        if not text:
            return
        chunks = [text[pos : pos + DOCS_INSERT_CHUNK_SIZE] for pos in range(0, len(text), DOCS_INSERT_CHUNK_SIZE)]
        for chunk in reversed(chunks):
            self._execute_requests(
                docs,
                doc_id,
                [{"insertText": {"location": {"index": index}, "text": chunk}}],
            )

    def _google_error_label(self, prefix: str, exc: HttpError) -> str:
        message = ""
        try:
            payload = json.loads(exc.content.decode("utf-8", errors="replace"))
            message = payload.get("error", {}).get("message", "")
        except Exception:
            message = str(exc)
        message = " ".join(message.split())
        if len(message) > 180:
            message = message[:177].rstrip() + "..."
        return f"{prefix}:{exc.status_code}:{message}" if message else f"{prefix}:{exc.status_code}"

    def _credentials_configuration_note(self) -> str | None:
        auth_mode = (self.auth_mode or "service_account").strip().lower()
        if auth_mode in {"oauth", "oauth_user", "user"}:
            if not self.oauth_token_json:
                return "GOOGLE_OAUTH_TOKEN_JSON is not configured."
            if not Path(self.oauth_token_json).exists():
                return f"OAuth token JSON not found: {self.oauth_token_json}"
            return None
        if auth_mode == "auto" and self.oauth_token_json and Path(self.oauth_token_json).exists():
            return None
        if not self.service_account_json:
            return "GOOGLE_SERVICE_ACCOUNT_JSON is not configured."
        service_account_path = Path(self.service_account_json)
        if not service_account_path.exists():
            return f"Service account JSON not found: {service_account_path}"
        return None

    def _credentials(self, scopes: list[str]):
        auth_mode = (self.auth_mode or "service_account").strip().lower()
        if auth_mode in {"oauth", "oauth_user", "user"}:
            return self._oauth_credentials(scopes)
        if auth_mode == "auto" and self.oauth_token_json and Path(self.oauth_token_json).exists():
            return self._oauth_credentials(scopes)
        return ServiceAccountCredentials.from_service_account_file(str(self.service_account_json), scopes=scopes)

    def _oauth_credentials(self, scopes: list[str]) -> UserCredentials:
        if not self.oauth_token_json:
            raise ValueError("GOOGLE_OAUTH_TOKEN_JSON is not configured.")
        token_path = Path(self.oauth_token_json)
        creds = UserCredentials.from_authorized_user_file(str(token_path), scopes=scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _upsert_google_sheet_row(
        self,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        doc_url: str | None,
    ) -> int | None:
        if not self.sheets_id:
            return None

        creds = self._credentials(SHEET_SCOPES)
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

    def _render_doc_text(
        self,
        meeting: MeetingMetadata,
        artifacts: MeetingArtifacts,
        transcript_doc_url: str | None = None,
    ) -> str:
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
            f"- Summary Doc: {self.current_doc_url() or '-'}",
            f"- Transcript Doc: {transcript_doc_url or self.current_transcript_doc_url() or '-'}",
            f"- Transcript section: {self.transcript_section_title(meeting) if (transcript_doc_url or self.current_transcript_doc_url()) else '-'}",
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
            "transcript_doc_url": None,
            "google_sheet_row": None,
            "note": note,
        }

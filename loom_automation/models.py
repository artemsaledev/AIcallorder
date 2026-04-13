from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class MeetingMetadata(BaseModel):
    loom_video_id: str
    source_url: str
    title: str
    meeting_type: str = "general"
    recorded_at: Optional[datetime] = None
    participants: List[str] = Field(default_factory=list)


class MeetingTranscript(BaseModel):
    meeting: MeetingMetadata
    transcript_text: str
    language: str = "auto"


class ActionItem(BaseModel):
    title: str
    owner: Optional[str] = None
    due_date: Optional[date] = None
    status: str = "open"


class BusinessTask(BaseModel):
    title: str
    context: str = ""
    requested_by: Optional[str] = None
    priority: str = "unknown"
    estimate_notes: str = ""


class TechnicalSpecDraft(BaseModel):
    title: str = ""
    goal: str = ""
    business_context: str = ""
    scope: List[str] = Field(default_factory=list)
    functional_requirements: List[str] = Field(default_factory=list)
    non_functional_requirements: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_string(cls, value):
        if isinstance(value, str):
            return {
                "title": "Legacy technical spec draft",
                "goal": value,
            }
        return value


class MeetingArtifacts(BaseModel):
    summary: str
    decisions: List[str] = Field(default_factory=list)
    completed_today: List[str] = Field(default_factory=list)
    remaining_tech_debt: List[str] = Field(default_factory=list)
    business_requests_for_estimation: List[BusinessTask] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    technical_spec_draft: TechnicalSpecDraft = Field(default_factory=TechnicalSpecDraft)
    telegram_digest: str = ""


class DailyDigestArtifacts(BaseModel):
    report_date: date
    summary: str
    completed_today: List[str] = Field(default_factory=list)
    remaining_tech_debt: List[str] = Field(default_factory=list)
    business_requests_for_estimation: List[BusinessTask] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    telegram_digest: str = ""


class ProcessMeetingRequest(BaseModel):
    collector_source: str = "loom"
    loom_video_id: Optional[str] = None
    loom_url: Optional[str] = None
    transcript_text: Optional[str] = None
    local_video_path: Optional[str] = None
    local_video_folder: Optional[str] = None
    title: str = "Loom meeting"
    meeting_type: str = "general"
    llm_provider: Optional[str] = None
    transcript_preprocess_enabled: Optional[bool] = None


class ProcessFolderRequest(BaseModel):
    folder_path: str
    meeting_type: str = "discord-sync"
    llm_provider: Optional[str] = None
    transcript_preprocess_enabled: Optional[bool] = None


class LoomImportRequest(BaseModel):
    limit: int = 5
    meeting_type: str = "discord-sync"
    llm_provider: Optional[str] = None
    transcript_preprocess_enabled: Optional[bool] = None
    primary_text_query: Optional[str] = None
    primary_date_query: Optional[date] = None
    search_results_limit: int = 10
    title_include_keywords: List[str] = Field(default_factory=list)
    title_exclude_keywords: List[str] = Field(default_factory=list)
    recorded_date_from: Optional[date] = None
    recorded_date_to: Optional[date] = None


class DailyDigestRequest(BaseModel):
    report_date: date

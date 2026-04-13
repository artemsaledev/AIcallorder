from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(default="sqlite:///./data/loom_automation.db", alias="DATABASE_URL")

    loom_email: Optional[str] = Field(default=None, alias="LOOM_EMAIL")
    loom_password: Optional[str] = Field(default=None, alias="LOOM_PASSWORD")
    loom_workspace_id: Optional[str] = Field(default=None, alias="LOOM_WORKSPACE_ID")
    loom_library_url: str = Field(default="https://www.loom.com/looms/videos", alias="LOOM_LIBRARY_URL")
    loom_transcript_source: str = Field(default="meeting_ai", alias="LOOM_TRANSCRIPT_SOURCE")
    loom_use_selenium_fallback: bool = Field(default=False, alias="LOOM_USE_SELENIUM_FALLBACK")
    loom_headless: bool = Field(default=True, alias="LOOM_HEADLESS")
    collector_source: str = Field(default="loom", alias="COLLECTOR_SOURCE")
    local_video_folder: Optional[str] = Field(default=None, alias="LOCAL_VIDEO_FOLDER")
    loom_title_include_keywords: str = Field(default="", alias="LOOM_TITLE_INCLUDE_KEYWORDS")
    loom_title_exclude_keywords: str = Field(default="", alias="LOOM_TITLE_EXCLUDE_KEYWORDS")
    prompt_routes_path: str = Field(default="promts/prompt_routes.json", alias="PROMPT_ROUTES_PATH")
    transcript_preprocess_enabled: bool = Field(default=True, alias="TRANSCRIPT_PREPROCESS_ENABLED")
    default_transcript_prompt_path: str = Field(default="promts/promts_transcription.txt", alias="DEFAULT_TRANSCRIPT_PROMPT_PATH")

    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_transcription_model: str = Field(default="gpt-4o-mini-transcribe", alias="OPENAI_TRANSCRIPTION_MODEL")
    llm_provider: str = Field(default="auto", alias="LLM_PROVIDER")
    llm_api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    llm_base_url: Optional[str] = Field(default=None, alias="LLM_BASE_URL")
    llm_model: Optional[str] = Field(default=None, alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=120, alias="LLM_TIMEOUT_SECONDS")

    local_llm_command: Optional[str] = Field(default=None, alias="LOCAL_LLM_COMMAND")
    local_llm_model_path: Optional[str] = Field(default=None, alias="LOCAL_LLM_MODEL_PATH")
    local_whisper_command: Optional[str] = Field(default=None, alias="LOCAL_WHISPER_COMMAND")
    local_whisper_model: str = Field(default="medium", alias="LOCAL_WHISPER_MODEL")
    prefer_local_whisper_for_local_files: bool = Field(default=True, alias="PREFER_LOCAL_WHISPER_FOR_LOCAL_FILES")

    google_service_account_json: Optional[str] = Field(default=None, alias="GOOGLE_SERVICE_ACCOUNT_JSON")
    google_docs_folder_id: Optional[str] = Field(default=None, alias="GOOGLE_DOCS_FOLDER_ID")
    google_doc_id: Optional[str] = Field(default=None, alias="GOOGLE_DOC_ID")
    google_sheets_id: Optional[str] = Field(default=None, alias="GOOGLE_SHEETS_ID")
    google_sheets_worksheet: str = Field(default="Transcript", alias="GOOGLE_SHEETS_WORKSHEET")

    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    webhook_shared_secret: Optional[str] = Field(default=None, alias="WEBHOOK_SHARED_SECRET")

    scheduler_enabled: bool = Field(default=False, alias="SCHEDULER_ENABLED")
    scheduler_meeting_type: str = Field(default="discord-sync", alias="SCHEDULER_MEETING_TYPE")
    scheduler_local_folder_enabled: bool = Field(default=False, alias="SCHEDULER_LOCAL_FOLDER_ENABLED")
    scheduler_local_folder_minutes: int = Field(default=30, alias="SCHEDULER_LOCAL_FOLDER_MINUTES")
    scheduler_loom_enabled: bool = Field(default=False, alias="SCHEDULER_LOOM_ENABLED")
    scheduler_loom_minutes: int = Field(default=30, alias="SCHEDULER_LOOM_MINUTES")
    scheduler_loom_limit: int = Field(default=3, alias="SCHEDULER_LOOM_LIMIT")
    scheduler_loom_library_url: Optional[str] = Field(default=None, alias="SCHEDULER_LOOM_LIBRARY_URL")
    scheduler_active_from: str = Field(default="08:00", alias="SCHEDULER_ACTIVE_FROM")
    scheduler_active_to: str = Field(default="21:00", alias="SCHEDULER_ACTIVE_TO")
    scheduler_active_weekdays: str = Field(default="mon,tue,wed,thu,fri", alias="SCHEDULER_ACTIVE_WEEKDAYS")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

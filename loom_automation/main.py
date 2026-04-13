from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
import html
import json
from pathlib import Path

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse

from loom_automation.config import get_settings
from loom_automation.integrations.google_workspace import GoogleWorkspacePublisher
from loom_automation.integrations.loom import LoomClient
from loom_automation.integrations.storage import SQLiteStorage
from loom_automation.integrations.telegram import TelegramNotifier
from loom_automation.models import DailyDigestRequest, LoomImportRequest, ProcessFolderRequest, ProcessMeetingRequest
from loom_automation.scheduler import AutomationScheduler
from loom_automation.workflow import AutomationWorkflow

settings = get_settings()

workflow = AutomationWorkflow(
    loom_client=LoomClient(
        transcript_source=settings.loom_transcript_source,
        use_selenium_fallback=settings.loom_use_selenium_fallback,
        library_url=settings.loom_library_url,
        loom_title_include_keywords=settings.loom_title_include_keywords,
        loom_title_exclude_keywords=settings.loom_title_exclude_keywords,
        prompt_routes_path=settings.prompt_routes_path,
        transcript_preprocess_enabled=settings.transcript_preprocess_enabled,
        default_transcript_prompt_path=settings.default_transcript_prompt_path,
        email=settings.loom_email,
        password=settings.loom_password,
        headless=settings.loom_headless,
        openai_api_key=settings.openai_api_key,
        openai_base_url=settings.openai_base_url,
        openai_model=settings.openai_model,
        openai_transcription_model=settings.openai_transcription_model,
        llm_provider=settings.llm_provider,
        llm_api_key=settings.llm_api_key,
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        llm_timeout_seconds=settings.llm_timeout_seconds,
        local_llm_command=settings.local_llm_command,
        local_whisper_command=settings.local_whisper_command,
        local_whisper_model=settings.local_whisper_model,
        prefer_local_whisper_for_local_files=settings.prefer_local_whisper_for_local_files,
    ),
    storage=SQLiteStorage(settings.database_url),
    google_publisher=GoogleWorkspacePublisher(
        service_account_json=settings.google_service_account_json,
        docs_folder_id=settings.google_docs_folder_id,
        doc_id=settings.google_doc_id,
        sheets_id=settings.google_sheets_id,
        worksheet_name=settings.google_sheets_worksheet,
    ),
    telegram_notifier=TelegramNotifier(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    ),
)

scheduler = AutomationScheduler(
    workflow=workflow,
    enabled=settings.scheduler_enabled,
    meeting_type=settings.scheduler_meeting_type,
    local_folder_enabled=settings.scheduler_local_folder_enabled,
    local_folder_path=settings.local_video_folder,
    local_folder_minutes=settings.scheduler_local_folder_minutes,
    loom_enabled=settings.scheduler_loom_enabled,
    loom_minutes=settings.scheduler_loom_minutes,
    loom_limit=settings.scheduler_loom_limit,
    loom_library_url=settings.scheduler_loom_library_url or settings.loom_library_url,
    active_from=settings.scheduler_active_from,
    active_to=settings.scheduler_active_to,
    active_weekdays=settings.scheduler_active_weekdays,
    settings_path=str(Path("data") / "scheduler_settings.json"),
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(title="AIcallorder", version="0.1.0", lifespan=lifespan)


def _page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg-1: #f7f4ec;
      --bg-2: #edf5f7;
      --card: rgba(255, 255, 255, 0.92);
      --ink: #1d2733;
      --muted: #567082;
      --line: #d6e2e7;
      --accent: #0b6b57;
      --accent-soft: #e8f6f1;
      --result: #111827;
      --result-ink: #f9fafb;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(235, 221, 187, 0.8), transparent 28%),
        radial-gradient(circle at top right, rgba(183, 220, 230, 0.8), transparent 28%),
        linear-gradient(180deg, var(--bg-1) 0%, var(--bg-2) 100%);
    }}

    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 28px 16px 56px;
    }}

    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 14px 36px rgba(0, 0, 0, 0.05);
      margin-bottom: 18px;
    }}

    h1 {{
      margin: 0 0 8px;
      font-size: 38px;
      line-height: 1.05;
    }}

    h2 {{
      margin: 0 0 10px;
      font-size: 22px;
    }}

    p {{
      margin: 0;
      line-height: 1.6;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}

    .summary-box {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: #f8fcfd;
    }}

    .summary-box strong {{
      display: block;
      margin-bottom: 6px;
    }}

    .mode-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}

    .mode-card {{
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      background: #fbfdff;
      cursor: pointer;
      transition: transform 140ms ease, box-shadow 140ms ease, border-color 140ms ease;
    }}

    .mode-card:hover {{
      transform: translateY(-1px);
      border-color: #86ad9d;
      box-shadow: 0 10px 24px rgba(0, 0, 0, 0.05);
    }}

    .mode-card.active {{
      background: var(--accent-soft);
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(11, 107, 87, 0.10);
    }}

    .mode-title {{
      font-weight: 700;
      margin-bottom: 6px;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}

    .section {{
      padding-top: 14px;
      border-top: 1px solid #e6eef2;
      margin-top: 14px;
    }}

    .field-group.hidden {{
      display: none;
    }}

    label {{
      display: block;
      margin: 14px 0 6px;
      font-weight: 600;
    }}

    input, textarea {{
      width: 100%;
      border: 1px solid #c9d5dd;
      border-radius: 12px;
      background: white;
      padding: 11px 12px;
      color: var(--ink);
      font: inherit;
    }}

    textarea {{
      min-height: 220px;
      resize: vertical;
    }}

    .hint {{
      color: var(--muted);
      font-size: 14px;
      margin-top: 6px;
    }}

    .toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}

    button, .button {{
      appearance: none;
      border: 0;
      text-decoration: none;
      border-radius: 999px;
      padding: 12px 18px;
      font-weight: 700;
      cursor: pointer;
      background: var(--accent);
      color: white;
    }}

    .ghost {{
      background: transparent;
      color: var(--accent);
      border: 1px solid var(--accent);
    }}

    pre {{
      background: var(--result);
      color: var(--result-ink);
      border-radius: 16px;
      padding: 18px;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
      overflow: auto;
    }}

    @media (max-width: 720px) {{
      h1 {{
        font-size: 32px;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    {body}
  </div>
</body>
</html>"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.app_env}


def _scheduler_summary_html() -> str:
    status = scheduler.status()
    local_task = status["tasks"]["local_folder"]
    loom_task = status["tasks"]["loom_import"]
    return f"""
    <div class="card">
      <h2>Scheduler</h2>
      <p>Фоновый режим можно включить один раз и дальше сервис будет сам подбирать новые Loom transcript и новые локальные файлы из выбранной папки.</p>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Scheduler</strong>
          {"enabled" if status["enabled"] else "disabled"}
        </div>
        <div class="summary-box">
          <strong>Watched folder</strong>
          {html.escape(status.get("local_folder_path") or "not set")}
        </div>
        <div class="summary-box">
          <strong>Local folder task</strong>
          {html.escape(local_task["last_status"])} / every {local_task["interval_minutes"]} min
        </div>
        <div class="summary-box">
          <strong>Loom import task</strong>
          {html.escape(loom_task["last_status"])} / every {loom_task["interval_minutes"]} min
        </div>
        <div class="summary-box">
          <strong>Loom folder URL</strong>
          {html.escape(status.get("loom_library_url") or "not set")}
        </div>
        <div class="summary-box">
          <strong>Active window</strong>
          {html.escape(status["active_from"])}-{html.escape(status["active_to"])} / {html.escape(status["active_weekdays"])}
        </div>
      </div>

      <form class="section" method="post" action="/ui/scheduler">
        <div class="grid">
          <div>
            <label for="scheduler_enabled">Scheduler enabled</label>
            <input id="scheduler_enabled" name="scheduler_enabled" value={"true" if status["enabled"] else "false"} />
            <div class="hint">Use <code>true</code> or <code>false</code>.</div>
          </div>
          <div>
            <label for="scheduler_meeting_type">Meeting type</label>
            <input id="scheduler_meeting_type" name="scheduler_meeting_type" value="{html.escape(status['meeting_type'])}" />
          </div>
          <div>
            <label for="scheduler_local_folder_enabled">Watched folder enabled</label>
            <input id="scheduler_local_folder_enabled" name="scheduler_local_folder_enabled" value={"true" if local_task["enabled"] else "false"} />
          </div>
          <div>
            <label for="scheduler_local_folder_minutes">Watched folder interval</label>
            <input id="scheduler_local_folder_minutes" name="scheduler_local_folder_minutes" value="{local_task['interval_minutes']}" />
          </div>
          <div>
            <label for="scheduler_local_folder_path">Watched folder path</label>
            <input id="scheduler_local_folder_path" name="scheduler_local_folder_path" value="{html.escape(status.get('local_folder_path') or '')}" placeholder="C:\\Users\\...\\Zoom" />
          </div>
          <div>
            <label for="scheduler_loom_enabled">Loom import enabled</label>
            <input id="scheduler_loom_enabled" name="scheduler_loom_enabled" value={"true" if loom_task["enabled"] else "false"} />
          </div>
          <div>
            <label for="scheduler_loom_minutes">Loom interval</label>
            <input id="scheduler_loom_minutes" name="scheduler_loom_minutes" value="{loom_task['interval_minutes']}" />
          </div>
          <div>
            <label for="scheduler_loom_limit">Loom import limit</label>
            <input id="scheduler_loom_limit" name="scheduler_loom_limit" value="{scheduler.loom_limit}" />
          </div>
          <div>
            <label for="scheduler_loom_library_url">Loom folder URL</label>
            <input id="scheduler_loom_library_url" name="scheduler_loom_library_url" value="{html.escape(status.get('loom_library_url') or '')}" placeholder="https://www.loom.com/looms/videos/..." />
          </div>
          <div>
            <label for="scheduler_active_from">Active from</label>
            <input id="scheduler_active_from" name="scheduler_active_from" value="{html.escape(status['active_from'])}" />
          </div>
          <div>
            <label for="scheduler_active_to">Active to</label>
            <input id="scheduler_active_to" name="scheduler_active_to" value="{html.escape(status['active_to'])}" />
          </div>
          <div>
            <label for="scheduler_active_weekdays">Active weekdays</label>
            <input id="scheduler_active_weekdays" name="scheduler_active_weekdays" value="{html.escape(status['active_weekdays'])}" />
            <div class="hint">Example: <code>mon,tue,wed,thu,fri</code></div>
          </div>
        </div>
        <div class="toolbar">
          <button type="submit">Save Scheduler</button>
        </div>
      </form>

      <div class="toolbar">
        <form method="post" action="/ui/run-scheduler-local">
          <button type="submit" class="ghost">Run Watched Folder Now</button>
        </form>
        <form method="post" action="/ui/run-scheduler-loom">
          <button type="submit" class="ghost">Run Loom Import Now</button>
        </form>
      </div>
    </div>
    """


def _truncate(value: str | None, limit: int = 220) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip(" ,;:.") + "…"


def _operations_html() -> str:
    meetings = workflow.storage.list_recent_meetings(limit=12)
    runs = workflow.storage.list_recent_run_logs(limit=12)

    meeting_rows = []
    for item in meetings:
        title = html.escape(item["title"])
        loom_video_id = html.escape(item["loom_video_id"])
        meeting_type = html.escape(item.get("meeting_type") or "-")
        recorded_at = html.escape(item.get("recorded_at") or "-")
        source_url = html.escape(item.get("source_url") or "")
        summary = ""
        artifacts = item.get("artifacts") or {}
        if isinstance(artifacts, dict):
            summary = html.escape(_truncate(artifacts.get("summary", ""), 260))
        transcript_preview = html.escape(_truncate(item.get("transcript_text", ""), 320))
        meeting_rows.append(
            f"""
            <div class="summary-box">
              <strong>{title}</strong>
              <div class="hint">ID: <code>{loom_video_id}</code></div>
              <div class="hint">Type: <code>{meeting_type}</code> | Recorded: <code>{recorded_at}</code></div>
              <div class="hint">URL: <a href="{source_url}" target="_blank" rel="noreferrer">{source_url or 'n/a'}</a></div>
              <p style="margin-top:10px;"><strong>Summary</strong><br />{summary or 'No artifacts yet.'}</p>
              <p style="margin-top:10px;"><strong>Transcript preview</strong><br />{transcript_preview or 'No transcript preview.'}</p>
              <div class="toolbar">
                <form method="post" action="/ui/records/delete">
                  <input type="hidden" name="loom_video_id" value="{loom_video_id}" />
                  <button type="submit" class="ghost">Delete From Local DB</button>
                </form>
              </div>
            </div>
            """
        )

    run_rows = []
    for item in runs:
        summary = html.escape(json.dumps(item.get("summary", {}), ensure_ascii=False, indent=2))
        run_rows.append(
            f"""
            <div class="summary-box">
              <strong>#{item['id']} — {html.escape(item['run_type'])}</strong>
              <div class="hint">Status: <code>{html.escape(item['status'])}</code> | By: <code>{html.escape(item['initiated_by'])}</code></div>
              <div class="hint">Started: <code>{html.escape(item['started_at'])}</code></div>
              <div class="hint">Finished: <code>{html.escape(item['finished_at'])}</code></div>
              <pre style="margin-top:10px;">{summary}</pre>
            </div>
            """
        )

    return f"""
    <div class="card">
      <h2>Operations</h2>
      <p>Здесь можно посмотреть, что уже считается обработанным в локальной базе, и управлять журналом запусков без ручной работы с SQLite.</p>
      <div class="toolbar">
        <form method="post" action="/ui/records/clear">
          <button type="submit" class="ghost">Clear All Processed Records</button>
        </form>
        <form method="post" action="/ui/runs/clear">
          <button type="submit" class="ghost">Clear Run Logs</button>
        </form>
      </div>
      <div class="section">
        <h2>Recent Processed Meetings</h2>
        <div class="summary-grid">
          {''.join(meeting_rows) or '<p>No processed meetings yet.</p>'}
        </div>
      </div>
      <div class="section">
        <h2>Recent Run Logs</h2>
        <div class="summary-grid">
          {''.join(run_rows) or '<p>No run logs yet.</p>'}
        </div>
      </div>
    </div>
    """


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    default_folder = html.escape(settings.local_video_folder or "")
    default_include = html.escape(settings.loom_title_include_keywords or "")
    default_exclude = html.escape(settings.loom_title_exclude_keywords or "")
    default_provider = html.escape(settings.llm_provider or "auto")
    default_today = date.today().isoformat()
    body = f"""
    <div class="card">
      <h1>AIcallorder</h1>
      <p>Выбирай источник на каждый запуск: Loom с готовой транскрипцией, один локальный файл или целую папку локальных записей. Форма запоминает последние введенные значения в браузере.</p>
      <div class="summary-grid">
        <div class="summary-box">
          <strong>Loom transcript</strong>
          Используй Loom URL и готовый transcript, если Loom уже его сгенерировал.
        </div>
        <div class="summary-box">
          <strong>Loom auto import</strong>
          Автоматический поиск новых Loom-видео в library и импорт только новых transcript.
        </div>
        <div class="summary-box">
          <strong>Local file</strong>
          Один Zoom, Discord или учебный ролик через локальный faster-whisper.
        </div>
        <div class="summary-box">
          <strong>Local folder</strong>
          Пакетная обработка целой папки с видеофайлами.
        </div>
      </div>
    </div>

    <form class="card" method="post" action="/ui/process">
      <input type="hidden" id="source_mode" name="source_mode" value="loom" />

      <h2>Source</h2>
      <div class="mode-grid">
        <div class="mode-card active" data-mode="loom">
          <div class="mode-title">Loom transcript</div>
          <div class="hint">Loom URL + вставка готовой транскрипции.</div>
        </div>
        <div class="mode-card" data-mode="loom-auto">
          <div class="mode-title">Loom auto import</div>
          <div class="hint">Взять новую порцию Loom-видео напрямую из library.</div>
        </div>
        <div class="mode-card" data-mode="local-file">
          <div class="mode-title">Local file</div>
          <div class="hint">Один локальный видеофайл на обработку.</div>
        </div>
        <div class="mode-card" data-mode="local-folder">
          <div class="mode-title">Local folder</div>
          <div class="hint">Обработка всех поддерживаемых файлов в папке.</div>
        </div>
      </div>

      <div class="section grid">
        <div>
          <label for="meeting_type">Meeting type</label>
          <input id="meeting_type" name="meeting_type" value="discord-sync" />
        </div>
        <div>
          <label for="title">Title</label>
          <input id="title" name="title" value="Loom meeting" />
        </div>
      </div>

      <div class="section grid">
        <div>
          <label for="llm_provider">Processing engine</label>
          <input id="llm_provider" name="llm_provider" value="{default_provider}" />
          <div class="hint">Use <code>openai</code>, <code>local</code> or <code>auto</code>.</div>
        </div>
        <div>
          <label for="transcript_preprocess_enabled">Transcript cleanup before summary</label>
          <input id="transcript_preprocess_enabled" name="transcript_preprocess_enabled" value={"true" if settings.transcript_preprocess_enabled else "false"} />
          <div class="hint">Use <code>true</code> to apply your external transcript prompt before summarization.</div>
        </div>
      </div>

      <div id="loom-auto-fields" class="field-group section hidden">
        <label for="loom_limit">How many new Loom items to import</label>
        <input id="loom_limit" name="loom_limit" value="5" />
        <div class="hint">Collector возьмет только новые Loom-видео, которых еще нет в локальной базе.</div>
        <div class="grid">
          <div>
            <label for="loom_primary_text_query">Primary text key</label>
            <input id="loom_primary_text_query" name="loom_primary_text_query" value="#daily" placeholder="#daily" />
            <div class="hint">Loom search first tries this text key before fallback scrolling.</div>
          </div>
          <div>
            <label for="loom_primary_date_query">Primary date key</label>
            <input id="loom_primary_date_query" name="loom_primary_date_query" type="date" value="{default_today}" />
            <div class="hint">Use the exact day you want to find in Loom.</div>
          </div>
          <div>
            <label for="loom_search_results_limit">Search depth limit</label>
            <input id="loom_search_results_limit" name="loom_search_results_limit" value="8" />
            <div class="hint">Maximum Loom search results to inspect before stopping.</div>
          </div>
          <div>
            <label for="loom_title_include_keywords">Loom include keywords</label>
            <input id="loom_title_include_keywords" name="loom_title_include_keywords" value="{default_include}" placeholder="оплат,заказ,доставк,ina" />
          </div>
          <div>
            <label for="loom_title_exclude_keywords">Loom exclude keywords</label>
            <input id="loom_title_exclude_keywords" name="loom_title_exclude_keywords" value="{default_exclude}" placeholder="обучение,tutorial,demo" />
          </div>
          <div>
            <label for="loom_recorded_date_from">Video date from</label>
            <input id="loom_recorded_date_from" name="loom_recorded_date_from" type="date" />
            <div class="hint">Date filter works when the Loom video title contains a parseable date.</div>
          </div>
          <div>
            <label for="loom_recorded_date_to">Video date to</label>
            <input id="loom_recorded_date_to" name="loom_recorded_date_to" type="date" />
          </div>
        </div>
      </div>

      <div id="loom-fields" class="field-group section">
        <label for="loom_url">Loom URL</label>
        <input id="loom_url" name="loom_url" placeholder="https://www.loom.com/share/..." />

        <label for="transcript_text">Loom transcript</label>
        <textarea id="transcript_text" name="transcript_text" placeholder="Вставь сюда готовую транскрипцию из Loom"></textarea>
        <div class="hint">Для Loom-режима этот текст обязателен.</div>
      </div>

      <div id="local-file-fields" class="field-group section hidden">
        <label for="local_video_path">Local file path</label>
        <input id="local_video_path" name="local_video_path" placeholder="C:\\Users\\...\\video.mp4" />
        <div class="hint">Подходит для одного файла встречи или обучающего видео.</div>
      </div>

      <div id="local-folder-fields" class="field-group section hidden">
        <label for="folder_path">Local folder path</label>
        <input id="folder_path" name="folder_path" value="{default_folder}" placeholder="C:\\Users\\...\\Zoom\\meeting-folder" />
        <div class="hint">Будут обработаны все файлы с поддерживаемыми расширениями внутри папки.</div>
      </div>

      <div class="toolbar">
        <button type="submit">Run Processing</button>
        <button type="button" class="ghost" id="clear-memory">Clear Saved Values</button>
      </div>
    </form>

    {_scheduler_summary_html()}
    {_operations_html()}

    <script>
      const sourceInput = document.getElementById("source_mode");
      const cards = document.querySelectorAll(".mode-card");
      const loomAutoFields = document.getElementById("loom-auto-fields");
      const loomFields = document.getElementById("loom-fields");
      const localFileFields = document.getElementById("local-file-fields");
      const localFolderFields = document.getElementById("local-folder-fields");
      const storageKey = "aicallorder-ui-state";

      function setMode(mode) {{
        sourceInput.value = mode;
        cards.forEach(card => card.classList.toggle("active", card.dataset.mode === mode));
        loomAutoFields.classList.toggle("hidden", mode !== "loom-auto");
        loomFields.classList.toggle("hidden", mode !== "loom");
        localFileFields.classList.toggle("hidden", mode !== "local-file");
        localFolderFields.classList.toggle("hidden", mode !== "local-folder");
      }}

      cards.forEach(card => {{
        card.addEventListener("click", () => setMode(card.dataset.mode));
      }});

      function saveState() {{
        const payload = {{
            source_mode: sourceInput.value,
            meeting_type: document.getElementById("meeting_type").value,
            title: document.getElementById("title").value,
            llm_provider: document.getElementById("llm_provider").value,
            transcript_preprocess_enabled: document.getElementById("transcript_preprocess_enabled").value,
            loom_limit: document.getElementById("loom_limit").value,
            loom_primary_text_query: document.getElementById("loom_primary_text_query").value,
            loom_primary_date_query: document.getElementById("loom_primary_date_query").value,
            loom_search_results_limit: document.getElementById("loom_search_results_limit").value,
            loom_title_include_keywords: document.getElementById("loom_title_include_keywords").value,
            loom_title_exclude_keywords: document.getElementById("loom_title_exclude_keywords").value,
            loom_recorded_date_from: document.getElementById("loom_recorded_date_from").value,
            loom_recorded_date_to: document.getElementById("loom_recorded_date_to").value,
            loom_url: document.getElementById("loom_url").value,
            transcript_text: document.getElementById("transcript_text").value,
            local_video_path: document.getElementById("local_video_path").value,
            folder_path: document.getElementById("folder_path").value
        }};
        localStorage.setItem(storageKey, JSON.stringify(payload));
      }}

      function loadState() {{
        const raw = localStorage.getItem(storageKey);
        if (!raw) {{
          setMode("loom");
          return;
        }}

        try {{
          const state = JSON.parse(raw);
          if (state.source_mode) setMode(state.source_mode);
          for (const id of ["meeting_type", "title", "llm_provider", "transcript_preprocess_enabled", "loom_limit", "loom_primary_text_query", "loom_primary_date_query", "loom_search_results_limit", "loom_title_include_keywords", "loom_title_exclude_keywords", "loom_recorded_date_from", "loom_recorded_date_to", "loom_url", "transcript_text", "local_video_path", "folder_path"]) {{
            const el = document.getElementById(id);
            if (el && state[id] !== undefined) el.value = state[id];
          }}
        }} catch (_err) {{
          setMode("loom");
        }}
      }}

      document.querySelector("form").addEventListener("submit", saveState);
      document.getElementById("clear-memory").addEventListener("click", () => {{
        localStorage.removeItem(storageKey);
        window.location.reload();
      }});

      loadState();
    </script>
    """
    return _page_shell("AIcallorder", body)


@app.post("/meetings/process")
def process_meeting(request: ProcessMeetingRequest) -> dict:
    return workflow.process_meeting(request)


@app.post("/reports/daily")
def build_daily_digest(request: DailyDigestRequest) -> dict:
    return workflow.build_daily_digest(request)


@app.post("/loom/import-latest")
def import_latest_loom(request: LoomImportRequest) -> dict:
    return workflow.import_latest_loom(request)


@app.post("/meetings/process-folder")
def process_folder(request: ProcessFolderRequest) -> dict:
    return workflow.process_folder(request)


@app.get("/scheduler/status")
def scheduler_status() -> dict:
    return scheduler.status()


@app.get("/records/recent")
def recent_records(limit: int = 25) -> dict:
    return {"items": workflow.storage.list_recent_meetings(limit=limit)}


@app.get("/runs/recent")
def recent_runs(limit: int = 25) -> dict:
    return {"items": workflow.storage.list_recent_run_logs(limit=limit)}


@app.post("/scheduler/run-local-folder")
def scheduler_run_local_folder() -> dict:
    return scheduler.run_local_folder_now()


@app.post("/scheduler/run-loom-import")
def scheduler_run_loom_import() -> dict:
    return scheduler.run_loom_now()


@app.post("/scheduler/configure")
def scheduler_configure(
    scheduler_enabled: bool,
    scheduler_meeting_type: str,
    scheduler_local_folder_enabled: bool,
    scheduler_local_folder_path: str | None,
    scheduler_local_folder_minutes: int,
    scheduler_loom_enabled: bool,
    scheduler_loom_minutes: int,
    scheduler_loom_limit: int,
    scheduler_loom_library_url: str | None,
    scheduler_active_from: str,
    scheduler_active_to: str,
    scheduler_active_weekdays: str,
) -> dict:
    return scheduler.configure(
        enabled=scheduler_enabled,
        meeting_type=scheduler_meeting_type,
        local_folder_enabled=scheduler_local_folder_enabled,
        local_folder_path=scheduler_local_folder_path,
        local_folder_minutes=scheduler_local_folder_minutes,
        loom_enabled=scheduler_loom_enabled,
        loom_minutes=scheduler_loom_minutes,
        loom_limit=scheduler_loom_limit,
        loom_library_url=scheduler_loom_library_url,
        active_from=scheduler_active_from,
        active_to=scheduler_active_to,
        active_weekdays=scheduler_active_weekdays,
    )


@app.post("/ui/process", response_class=HTMLResponse)
def ui_process(
    source_mode: str = Form(...),
    meeting_type: str = Form("discord-sync"),
    title: str = Form("Loom meeting"),
    llm_provider: str = Form("auto"),
    transcript_preprocess_enabled: str = Form("true"),
    loom_limit: str = Form("5"),
    loom_primary_text_query: str = Form(""),
    loom_primary_date_query: str = Form(""),
    loom_search_results_limit: str = Form("8"),
    loom_title_include_keywords: str = Form(""),
    loom_title_exclude_keywords: str = Form(""),
    loom_recorded_date_from: str = Form(""),
    loom_recorded_date_to: str = Form(""),
    loom_url: str = Form(""),
    transcript_text: str = Form(""),
    local_video_path: str = Form(""),
    folder_path: str = Form(""),
) -> str:
    parsed_llm_provider = llm_provider.strip().lower() or "auto"
    preprocess_enabled = transcript_preprocess_enabled.strip().lower() == "true"
    include_keywords = [item.strip() for item in loom_title_include_keywords.replace(";", ",").split(",") if item.strip()]
    exclude_keywords = [item.strip() for item in loom_title_exclude_keywords.replace(";", ",").split(",") if item.strip()]
    recorded_date_from = loom_recorded_date_from.strip() or None
    recorded_date_to = loom_recorded_date_to.strip() or None
    if source_mode == "loom-auto":
        result = workflow.import_latest_loom(
            LoomImportRequest(
                limit=max(1, int(loom_limit or "5")),
                meeting_type=meeting_type,
                llm_provider=parsed_llm_provider,
                transcript_preprocess_enabled=preprocess_enabled,
                primary_text_query=loom_primary_text_query.strip() or None,
                primary_date_query=loom_primary_date_query.strip() or None,
                search_results_limit=max(1, int(loom_search_results_limit or "8")),
                title_include_keywords=include_keywords,
                title_exclude_keywords=exclude_keywords,
                recorded_date_from=recorded_date_from,
                recorded_date_to=recorded_date_to,
            )
        )
    elif source_mode == "local-folder":
        result = workflow.process_folder(
            ProcessFolderRequest(
                folder_path=folder_path,
                meeting_type=meeting_type,
                llm_provider=parsed_llm_provider,
                transcript_preprocess_enabled=preprocess_enabled,
            )
        )
    else:
        result = workflow.process_meeting(
            ProcessMeetingRequest(
                collector_source=source_mode,
                loom_url=loom_url or None,
                transcript_text=transcript_text or None,
                local_video_path=local_video_path or None,
                title=title,
                meeting_type=meeting_type,
                llm_provider=parsed_llm_provider,
                transcript_preprocess_enabled=preprocess_enabled,
            )
        )

    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Run Result</h1>
      <p>Обработка завершена. Ниже полный JSON-результат текущего запуска.</p>
      <div class="toolbar">
        <a class="button" href="/">Back To Form</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("AIcallorder Result", body)


@app.post("/ui/scheduler", response_class=HTMLResponse)
def ui_scheduler(
    scheduler_enabled: str = Form("false"),
    scheduler_meeting_type: str = Form("discord-sync"),
    scheduler_local_folder_enabled: str = Form("false"),
    scheduler_local_folder_path: str = Form(""),
    scheduler_local_folder_minutes: str = Form("30"),
    scheduler_loom_enabled: str = Form("false"),
    scheduler_loom_minutes: str = Form("30"),
    scheduler_loom_limit: str = Form("3"),
    scheduler_loom_library_url: str = Form(""),
    scheduler_active_from: str = Form("08:00"),
    scheduler_active_to: str = Form("21:00"),
    scheduler_active_weekdays: str = Form("mon,tue,wed,thu,fri"),
) -> str:
    result = scheduler.configure(
        enabled=scheduler_enabled.strip().lower() == "true",
        meeting_type=scheduler_meeting_type,
        local_folder_enabled=scheduler_local_folder_enabled.strip().lower() == "true",
        local_folder_path=scheduler_local_folder_path.strip() or None,
        local_folder_minutes=max(1, int(scheduler_local_folder_minutes or "30")),
        loom_enabled=scheduler_loom_enabled.strip().lower() == "true",
        loom_minutes=max(1, int(scheduler_loom_minutes or "30")),
        loom_limit=max(1, int(scheduler_loom_limit or "3")),
        loom_library_url=scheduler_loom_library_url.strip() or None,
        active_from=scheduler_active_from.strip() or "08:00",
        active_to=scheduler_active_to.strip() or "21:00",
        active_weekdays=scheduler_active_weekdays.strip() or "mon,tue,wed,thu,fri",
    )
    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Scheduler Saved</h1>
      <p>Новые настройки сохранены и будут использоваться после текущего запуска и после перезапуска сервиса.</p>
      <div class="toolbar">
        <a class="button" href="/">Back To Dashboard</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("Scheduler Saved", body)


@app.post("/ui/run-scheduler-local", response_class=HTMLResponse)
def ui_run_scheduler_local() -> str:
    result = scheduler.run_local_folder_now()
    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Watched Folder Run</h1>
      <div class="toolbar">
        <a class="button" href="/">Back To Dashboard</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("Watched Folder Run", body)


@app.post("/ui/run-scheduler-loom", response_class=HTMLResponse)
def ui_run_scheduler_loom() -> str:
    result = scheduler.run_loom_now()
    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Loom Import Run</h1>
      <div class="toolbar">
        <a class="button" href="/">Back To Dashboard</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("Loom Import Run", body)


@app.post("/ui/records/delete", response_class=HTMLResponse)
def ui_delete_record(loom_video_id: str = Form(...)) -> str:
    deleted = workflow.storage.delete_meeting(loom_video_id.strip())
    result = {
        "deleted": deleted,
        "loom_video_id": loom_video_id.strip(),
        "next_step": "If this was a Loom record, the next matching Loom import can ingest it again.",
    }
    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Record Updated</h1>
      <p>Локальная база обработанных встреч обновлена.</p>
      <div class="toolbar">
        <a class="button" href="/">Back To Dashboard</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("Record Updated", body)


@app.post("/ui/records/clear", response_class=HTMLResponse)
def ui_clear_records() -> str:
    deleted_count = workflow.storage.clear_meetings()
    result = {
        "deleted_count": deleted_count,
        "next_step": "All videos are now considered unprocessed until they are imported again.",
    }
    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Processed Records Cleared</h1>
      <p>Локальная таблица обработанных встреч очищена.</p>
      <div class="toolbar">
        <a class="button" href="/">Back To Dashboard</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("Processed Records Cleared", body)


@app.post("/ui/runs/clear", response_class=HTMLResponse)
def ui_clear_run_logs() -> str:
    deleted_count = workflow.storage.clear_run_logs()
    result = {
        "deleted_count": deleted_count,
        "next_step": "Run history is empty now. New manual and scheduler runs will appear here again.",
    }
    pretty = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    body = f"""
    <div class="card">
      <h1>Run Logs Cleared</h1>
      <p>Журнал запусков очищен.</p>
      <div class="toolbar">
        <a class="button" href="/">Back To Dashboard</a>
      </div>
    </div>
    <pre>{pretty}</pre>
    """
    return _page_shell("Run Logs Cleared", body)


@app.post("/webhooks/loom")
def loom_webhook(payload: ProcessMeetingRequest, x_webhook_secret: str | None = Header(default=None)) -> dict:
    if settings.webhook_shared_secret and x_webhook_secret != settings.webhook_shared_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")
    return workflow.process_meeting(payload)

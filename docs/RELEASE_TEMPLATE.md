# AIcallorder Release Template

## Highlights

- Web-based control panel for Loom and local video processing
- Loom auto import with transcript extraction
- Local Whisper fallback for local files and folders
- OpenAI-compatible structured summarization
- Google Docs and Google Sheets publishing
- Telegram meeting and daily digests
- Built-in scheduler with operations dashboard

## Included In This Release

- Source selection for Loom transcript, Loom auto import, local file, and local folder
- Scheduler controls from the browser
- Processed-record management and run logs
- Temporary external access helpers
- Windows always-on scripts for local background startup

## Setup

1. Copy `.env.example` to `.env`
2. Fill in Loom, LLM, Google, and Telegram credentials
3. Install dependencies with `pip install -r requirements.txt`
4. Start locally with `python -m uvicorn loom_automation.main:app --host 127.0.0.1 --port 8000`

## Main Entry Points

- `loom_automation/main.py`
- `README.md`
- `scripts/start_web.ps1`

## Notes

- Secrets stay local and are excluded from Git
- SQLite processed-state is stored outside the repository index
- Temporary public tunnels are suitable for testing, not long-term production

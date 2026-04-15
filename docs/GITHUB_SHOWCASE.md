# GitHub Showcase Kit

## About Description

AIcallorder turns Loom recordings and local meeting videos into structured summaries, action items, technical specs, Telegram digests, and Google Workspace records through a browser-based automation dashboard.

## Website

Use:

- `https://app.artemai.uk`

## Suggested Topics

```text
loom
meeting-automation
transcription
telegram-bot
google-docs
google-sheets
openai
fastapi
selenium
whisper
xvfb
operations-dashboard
workflow-automation
llm
```

## Repository Short Pitch

AIcallorder is a local-first meeting operations service that auto-imports Loom videos, processes local recordings, generates structured artifacts, and publishes them to Google Workspace and Telegram.

## What Makes The Project Different

- It combines Loom import, local file processing, scheduling, and operations UI in one service.
- It keeps processed-state locally in SQLite, so deduplication does not depend on Google Sheets or chat history.
- It supports Linux VPS operation with `Xvfb` and a persistent browser profile for Loom / Atlassian sessions.
- It exposes run-history and scheduler diagnostics directly in the web UI.

## Suggested Screenshots

- `assets/dashboard-home.png` - main control panel
- `assets/social-preview.svg` - social / Open Graph preview asset

## Suggested GitHub Social Preview

Upload one of:

- `assets/social-preview.svg`
- `assets/dashboard-home.png`

## Suggested Pinned Highlights

- Loom auto import with transcript extraction
- Local folder transcription fallback
- OpenAI or local LLM summarization
- Google Docs / Sheets publishing
- Telegram meeting and daily digests
- Scheduler and operations dashboard
- Linux VPS mode with persistent Loom auth session

## Suggested README Links

Point visitors to:

- `README.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `deploy/linux/README.md`

## Demo Talking Points

1. Show the main browser dashboard.
2. Run a background Loom import from a selected Loom folder.
3. Show the generated meeting note in Google Docs.
4. Show the Telegram digest with Loom and Google Doc links.
5. Show processed records and run logs in the operations dashboard.
6. Mention that production uses a persistent Linux browser profile instead of disposable headless auth.

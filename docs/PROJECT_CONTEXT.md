# Project Context

This file is the compact source of truth for how AIcallorder works today, what is deployed in production, and what to read first when a future chat starts without prior context.

## Product Summary

AIcallorder turns Loom recordings and local meeting videos into structured delivery artifacts:

- meeting summaries
- action items
- tech debt notes
- business requests for estimation
- technical spec drafts
- Telegram digests
- Google Docs / Google Sheets records

Main public URL:

- `https://app.artemai.uk`

## Supported Modes

The web UI exposes four main processing modes:

- `Loom transcript`: manual reprocessing when you already have a Loom URL and transcript
- `Loom auto import`: collect new videos from a Loom library or folder
- `Local file`: process one local recording
- `Local folder`: batch-process local recordings

Recommended usage:

- recurring team meetings and daily syncs: `Loom auto import`
- one-off manual retry of a specific Loom meeting: `Loom transcript`
- Zoom / Discord / training recordings stored locally: `Local file` or `Local folder`

## High-Level Architecture

Core flow:

1. Collector gets transcript or media source from Loom or local storage.
2. Transcriber uses Loom transcript or local Whisper fallback.
3. Transcript cleanup runs optionally before summarization.
4. Summarizer generates structured artifacts.
5. Publishers write to Google Docs, Google Sheets, and Telegram.
6. Scheduler and operations UI manage recurring runs and diagnostics.

Key code entry points:

- `loom_automation/main.py`
- `loom_automation/workflow.py`
- `loom_automation/scheduler.py`
- `loom_automation/modules/collector.py`
- `loom_automation/pipelines/discord_loom.py`

## Production Topology

Current tested VPS deployment:

- domain: `app.artemai.uk`
- reverse proxy: `nginx`
- app service: `aicallorder.service`
- virtual display: `aicallorder-xvfb.service`
- service user: `deploy`
- app directory: `/opt/AIcallorder`
- app bind: `127.0.0.1:8000`
- display: `:99`
- browser profile: `/home/deploy/snap/chromium/common/aicallorder-profile`

Important system behavior:

- code is updated via `git pull`
- app is managed by `systemd`
- public traffic goes through `nginx`
- deduplication state lives in SQLite, not in Google artifacts

## Sources of Truth

Operational state on the server:

- app root: `/opt/AIcallorder`
- env file: `/opt/AIcallorder/.env`
- database: `/opt/AIcallorder/data/loom_automation.db`
- scheduler config: `/opt/AIcallorder/data/scheduler_settings.json`
- runtime diagnostics: `/opt/AIcallorder/data/runtime/logs/`

Source of truth by concern:

- processed-meeting deduplication: local SQLite
- scheduler settings: local JSON
- run history: local run logs / DB-backed UI records
- Google Docs / Sheets / Telegram: downstream outputs, not primary state

## Loom Authentication Model

Linux production uses:

- `LOOM_HEADLESS=false`
- `Xvfb`
- persistent browser profile
- real Chromium session rather than disposable strict-headless login

Why:

- Loom / Atlassian is more stable when treated like a normal browser profile
- email verification and 2FA challenges can appear on a fresh browser session
- once the challenge is completed inside the persistent profile, later scheduler runs can reuse that session

Known operational rule:

- if Atlassian asks for an email code or 2FA, complete it manually once inside the same persistent profile used by the service

## Recent Loom Auth Fixes

Recent fixes made to stabilize Linux Loom automation:

- `Run Loom Import Now` now queues work in the background instead of holding the page open on a long request
- timeout diagnostics preserve richer context for Loom failures
- nested Loom library paths like `/looms/videos/<folder>` are treated as valid library pages
- blocker detection no longer falsely interprets a normal library page as an email verification screen based on generic DOM text alone

This matters because previous server failures often showed:

- `Last URL: https://www.loom.com/looms/videos`
- `Last title: Videos | Library | Loom`

Those failures were sometimes false login-blocker detections rather than real authentication prompts.

## Fast Diagnostics

Public endpoints that are safe to inspect:

- `https://app.artemai.uk/health`
- `https://app.artemai.uk/scheduler/status`
- `https://app.artemai.uk/runs/recent?limit=5`
- `https://app.artemai.uk/records/recent?limit=20`

Server-local health check:

```bash
curl http://127.0.0.1:8000/health
```

Operational note:

- production timestamps exposed by the backend are UTC

## Deployment Workflow

Normal code update flow:

1. Pull code as `deploy`.
2. Restart services as `root`.
3. Verify `/health`.
4. Trigger or wait for a Loom scheduler run.
5. Inspect `/runs/recent` before going to raw server logs.

The detailed commands live in `docs/OPERATIONS_RUNBOOK.md`.

## Read This First in a New Chat

If a future chat starts cold, restore context in this order:

1. `README.md`
2. `docs/PROJECT_CONTEXT.md`
3. `docs/OPERATIONS_RUNBOOK.md`
4. `deploy/linux/README.md`
5. `docs/GITHUB_SHOWCASE.md`

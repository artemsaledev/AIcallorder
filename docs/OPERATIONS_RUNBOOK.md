# Operations Runbook

This runbook describes how to operate the current Linux production deployment, how to update it safely, and how to recover the Loom / Atlassian browser session when automation loses access.

## Public Checks

Use these first before opening server logs:

- `https://app.artemai.uk/health`
- `https://app.artemai.uk/scheduler/status`
- `https://app.artemai.uk/runs/recent?limit=5`
- `https://app.artemai.uk/records/recent?limit=20`

Notes:

- production timestamps are UTC
- recent run summaries are the fastest way to inspect scheduler failures without SSH

## Server Layout

Current production layout:

- app root: `/opt/AIcallorder`
- env file: `/opt/AIcallorder/.env`
- database: `/opt/AIcallorder/data/loom_automation.db`
- runtime logs: `/opt/AIcallorder/data/runtime/logs/`
- scheduler config: `/opt/AIcallorder/data/scheduler_settings.json`

Services:

- `aicallorder.service`
- `aicallorder-xvfb.service`

Runtime user:

- `deploy`

## Normal Update Procedure

Pull code as `deploy`:

```bash
su - deploy
cd /opt/AIcallorder
git pull origin main
git rev-parse --short HEAD
```

Restart and verify as `root`:

```bash
cd /opt/AIcallorder
systemctl restart aicallorder.service
sleep 3
curl http://127.0.0.1:8000/health
systemctl status aicallorder.service --no-pager -l
systemctl status aicallorder-xvfb.service --no-pager -l
```

Useful follow-up:

```bash
journalctl -u aicallorder.service -n 120 --no-pager
```

## Common Health Commands

Check app service:

```bash
systemctl status aicallorder.service --no-pager -l
```

Check Xvfb:

```bash
systemctl status aicallorder-xvfb.service --no-pager -l
```

Check local health endpoint:

```bash
curl http://127.0.0.1:8000/health
```

Tail recent app logs:

```bash
journalctl -u aicallorder.service -f
```

## Loom Auth Recovery via VNC

Use this only when Loom / Atlassian requires manual verification for the persistent browser profile.

### 1. Prepare server side

Stop only the web app if needed:

```bash
systemctl stop aicallorder.service
```

Ensure the virtual display is running:

```bash
systemctl start aicallorder-xvfb.service
systemctl status aicallorder-xvfb.service --no-pager -l
```

If `x11vnc` and `fluxbox` are missing:

```bash
apt-get update
apt-get install -y x11vnc fluxbox
```

Start a lightweight window manager and VNC bridge:

```bash
runuser -u deploy -- bash -lc 'DISPLAY=:99 fluxbox >/tmp/fluxbox.log 2>&1 &'
x11vnc -display :99 -rfbport 5900 -localhost -forever -shared -nopw
```

In a second server shell, launch Chromium with the same profile the service uses:

```bash
runuser -u deploy -- bash -lc 'export HOME=/home/deploy; DISPLAY=:99 /usr/bin/chromium-browser --user-data-dir=/home/deploy/snap/chromium/common/aicallorder-profile >/tmp/chromium-manual.log 2>&1 &'
```

### 2. Create the SSH tunnel from the local PC

Run this on your local machine, not on the server:

```powershell
ssh -N -L 5900:127.0.0.1:5900 root@173.242.60.148
```

Keep that terminal open while using VNC.

### 3. Connect with a VNC viewer

Open your VNC client and connect to:

```text
localhost:5900
```

### 4. Complete manual auth

Inside the remote Chromium session:

- open Loom if it is not already open
- sign in with the same workspace account used by automation
- complete Atlassian email verification or 2FA if prompted
- wait until the browser lands in the target Loom library or folder

Important:

- the goal is to authenticate the persistent profile, not just one temporary tab
- after successful login, the profile should keep the session for later scheduler runs

### 5. Return the app to normal mode

On the server:

```bash
pkill -u deploy -f 'chromedriver|chromium|google-chrome' || true
find /home/deploy/snap/chromium/common/aicallorder-profile -maxdepth 1 \( -name 'Singleton*' -o -name 'DevToolsActivePort' -o -name '.org.chromium.Chromium.*' \) -delete
systemctl start aicallorder.service
sleep 3
curl http://127.0.0.1:8000/health
```

Then trigger a manual Loom run from the UI and inspect:

- `https://app.artemai.uk/runs/recent?limit=5`

## Common Failures

### `502 Bad Gateway`

Usually means `nginx` cannot reach the local app.

Check:

```bash
systemctl status aicallorder.service --no-pager -l
curl http://127.0.0.1:8000/health
```

### `SessionNotCreatedException` / `Chrome instance exited`

Usually means Chromium could not start cleanly with the persistent profile.

Recovery:

```bash
pkill -u deploy -f 'chromedriver|chromium|google-chrome' || true
find /home/deploy/snap/chromium/common/aicallorder-profile -maxdepth 1 \( -name 'Singleton*' -o -name 'DevToolsActivePort' -o -name '.org.chromium.Chromium.*' \) -delete
systemctl restart aicallorder.service
```

### `TimeoutException` during Loom login

Interpret the message first via `/runs/recent`.

Common meanings:

- real Atlassian email verification or 2FA challenge
- browser opened Loom but was not fully authenticated
- older code revision falsely treated a library page as a blocker

If the error message references diagnostics files in `data/runtime/logs/`, inspect those snapshots on the server.

### Site works but scheduler keeps failing

Check:

- `https://app.artemai.uk/scheduler/status`
- `https://app.artemai.uk/runs/recent?limit=5`

Then verify:

- `LOOM_LIBRARY_URL`
- `LOOM_EMAIL`
- `LOOM_PASSWORD`
- `CHROME_BINARY`
- `CHROMEDRIVER_PATH`
- `CHROME_USER_DATA_DIR`

## Operational Rules

- Pull code as `deploy`
- Manage services as `root`
- Treat SQLite as the deduplication source of truth
- Prefer `/runs/recent` over screenshots or raw journal logs for first-pass diagnosis
- Keep the persistent Chromium profile stable; avoid deleting it unless you intentionally want to re-authenticate from scratch

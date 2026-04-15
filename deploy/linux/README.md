# Linux Deployment

This project runs on Linux VPS behind `nginx` with `systemd`, `Xvfb`, and a persistent non-headless browser session for Loom automation.

## Current Production Pattern

The currently tested deployment model is:

- `LOOM_HEADLESS=false`
- `DISPLAY=:99`
- `Xvfb` as a virtual display
- service user `deploy`
- persistent browser profile owned by the same service user
- app managed by `aicallorder.service`
- virtual display managed by `aicallorder-xvfb.service`

This mode is intentionally closer to the working local browser flow than disposable strict-headless automation.

## 1. Install runtime packages

From the repository root:

```bash
chmod +x deploy/linux/install_runtime_ubuntu.sh
./deploy/linux/install_runtime_ubuntu.sh
```

## 2. Configure `.env`

Minimum Linux Loom-related settings:

```env
LOOM_HEADLESS=false
CHROME_BINARY=/usr/bin/chromium-browser
CHROMEDRIVER_PATH=/snap/bin/chromium.chromedriver
CHROME_USER_DATA_DIR=/home/deploy/snap/chromium/common/aicallorder-profile
CHROME_WINDOW_SIZE=1600,1200
CHROME_EXTRA_ARGS=
```

Keep your existing app, Google, Telegram, OpenAI, and scheduler settings in the same `.env`.

If your VPS uses `google-chrome` instead of Chromium, update `CHROME_BINARY` and `CHROMEDRIVER_PATH` to match the installed binaries.

## 3. Install systemd units

Copy the templates and replace:

- `YOUR_LINUX_USER`
- `/opt/AIcallorder`

Files:

- `deploy/linux/systemd/aicallorder-xvfb.service.example`
- `deploy/linux/systemd/aicallorder-web.service.example`

Example:

```bash
sudo cp deploy/linux/systemd/aicallorder-xvfb.service.example /etc/systemd/system/aicallorder-xvfb.service
sudo cp deploy/linux/systemd/aicallorder-web.service.example /etc/systemd/system/aicallorder.service
sudo nano /etc/systemd/system/aicallorder-xvfb.service
sudo nano /etc/systemd/system/aicallorder.service
```

Then enable both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aicallorder-xvfb.service
sudo systemctl enable --now aicallorder.service
```

## 4. Verify

```bash
systemctl status aicallorder-xvfb.service
systemctl status aicallorder.service
journalctl -u aicallorder.service -n 200 --no-pager
curl http://127.0.0.1:8000/health
```

## Loom Authentication Notes

- A persistent browser profile helps Loom and Atlassian sessions behave more like a normal browser.
- If Atlassian prompts for extra verification, complete that once inside the same persistent profile.
- After changing Chrome or ChromeDriver on the server, restart both services.

## One-Time Manual Auth Recovery

If Loom import fails because Atlassian asks for email verification or 2FA, do a one-time manual login in the same persistent profile used by the service.

The full recovery flow is documented in:

- `docs/OPERATIONS_RUNBOOK.md`

High level:

1. Keep `aicallorder-xvfb.service` running.
2. Start `x11vnc` on display `:99`.
3. Open an SSH tunnel from the local machine to VNC port `5900`.
4. Launch Chromium as `deploy` with the same `CHROME_USER_DATA_DIR`.
5. Complete the Loom / Atlassian login challenge.
6. Stop manual browser processes and restart `aicallorder.service`.

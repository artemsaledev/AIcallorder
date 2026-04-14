# Linux Deployment

This project can run on a Linux VPS behind `nginx` with `systemd`, `Xvfb`, and a regular non-headless Chrome session.

## Recommended Server Mode

Use:

- `LOOM_HEADLESS=false`
- `DISPLAY=:99`
- `Xvfb` as a virtual display
- system-installed `google-chrome` and `chromedriver`
- a persistent Chrome user data directory

This mode is intentionally closer to the working local browser flow than strict headless automation.

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
CHROME_BINARY=/usr/bin/google-chrome
CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
CHROME_USER_DATA_DIR=/opt/aicallorder/data/chrome-profile
CHROME_WINDOW_SIZE=1600,1200
CHROME_EXTRA_ARGS=
```

Keep your existing app, Google, Telegram, OpenAI, and scheduler settings in the same `.env`.

## 3. Install systemd units

Copy the templates and replace:

- `YOUR_LINUX_USER`
- `/opt/aicallorder`

Files:

- `deploy/linux/systemd/aicallorder-xvfb.service.example`
- `deploy/linux/systemd/aicallorder-web.service.example`

Example:

```bash
sudo cp deploy/linux/systemd/aicallorder-xvfb.service.example /etc/systemd/system/aicallorder-xvfb.service
sudo cp deploy/linux/systemd/aicallorder-web.service.example /etc/systemd/system/aicallorder-web.service
sudo nano /etc/systemd/system/aicallorder-xvfb.service
sudo nano /etc/systemd/system/aicallorder-web.service
```

Then enable both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aicallorder-xvfb.service
sudo systemctl enable --now aicallorder-web.service
```

## 4. Verify

```bash
systemctl status aicallorder-xvfb.service
systemctl status aicallorder-web.service
journalctl -u aicallorder-web.service -n 200 --no-pager
curl http://127.0.0.1:8000/health
```

## Notes

- A persistent Chrome profile helps Loom and Atlassian sessions behave more like a normal browser.
- If Atlassian prompts for extra verification, complete that once inside the same persistent profile.
- After changing Chrome or ChromeDriver on the server, restart both services.

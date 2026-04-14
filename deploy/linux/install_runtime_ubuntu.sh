#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

sudo apt-get update
sudo apt-get install -y \
  curl \
  fonts-liberation \
  gnupg \
  libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libc6 \
  libcairo2 \
  libcups2 \
  libdbus-1-3 \
  libexpat1 \
  libgbm1 \
  libgcc-s1 \
  libglib2.0-0 \
  libgtk-3-0 \
  libnspr4 \
  libnss3 \
  libpango-1.0-0 \
  libpangocairo-1.0-0 \
  libstdc++6 \
  libx11-6 \
  libx11-xcb1 \
  libxcb1 \
  libxcomposite1 \
  libxcursor1 \
  libxdamage1 \
  libxext6 \
  libxfixes3 \
  libxi6 \
  libxrandr2 \
  libxrender1 \
  libxss1 \
  libxtst6 \
  python3-pip \
  python3-venv \
  unzip \
  wget \
  xdg-utils \
  xvfb

if ! command -v google-chrome >/dev/null 2>&1; then
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | \
    sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | \
    sudo tee /etc/apt/sources.list.d/google-chrome.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y google-chrome-stable
fi

CHROME_VERSION="$(google-chrome --version | awk '{print $3}')"
CHROME_MAJOR="${CHROME_VERSION%%.*}"
CHROMEDRIVER_VERSION="$(curl -fsSL "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_MAJOR}")"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
wget -q "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" -O "$TMP_DIR/chromedriver.zip"
unzip -q "$TMP_DIR/chromedriver.zip" -d "$TMP_DIR"
sudo install -m 0755 "$TMP_DIR/chromedriver-linux64/chromedriver" /usr/local/bin/chromedriver

"$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

mkdir -p "$PROJECT_DIR/data/chrome-profile"
mkdir -p "$PROJECT_DIR/data/runtime/logs"

echo "Runtime install complete."
echo "Chrome: $(google-chrome --version)"
echo "ChromeDriver: $(chromedriver --version)"

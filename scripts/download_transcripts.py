import os
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# 🔐 Авторизация в Google Sheets
SHEET_ID = "1MXJmoiCoHvN1y_Q3-rASXOfEVi-uKyhFo8aBzB76328"
SHEET_NAME = "Transcript"

# 🔗 Пути
DOWNLOAD_FOLDER = os.getenv("DOWNLOAD_FOLDER", "/app/downloads")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "/app/scripts/united-aura-440321-p2-c819703433e8.json",
)

# 🔑 Доступ в Loom
LOOM_EMAIL = os.getenv("LOOM_EMAIL")
LOOM_PASSWORD = os.getenv("LOOM_PASSWORD")
LOOM_LOGIN_URL = "https://www.loom.com/login"

# 📌 Настройки Chrome для Selenium
options = Options()
options.add_argument("--headless")  # Запуск без UI
options.add_argument("--disable-dev-shm-usage")  # Исправление ошибки с памятью
options.add_argument("--no-sandbox")  # Отключение песочницы (важно для Docker)
options.add_argument("--disable-gpu")  # Отключение GPU (не нужно в headless)
options.add_argument("--remote-debugging-port=9222")  # Включение дебага
prefs = {"download.default_directory": DOWNLOAD_FOLDER}
options.add_experimental_option("prefs", prefs)

# Создаем папку, если её нет
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)
    print(f"📂 Создана папка для загрузок: {DOWNLOAD_FOLDER}")

# 🚀 Запуск Chrome
CHROMEDRIVER_PATH = "/usr/local/bin/chromedriver"
driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
wait = WebDriverWait(driver, 15)


def authorize_google_sheets():
    """Авторизация в Google Sheets"""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SERVICE_ACCOUNT_JSON, scope)
    return gspread.authorize(creds)


def get_processed_transcripts():
    """Получение списка обработанных транскрипций"""
    client = authorize_google_sheets()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    records = sheet.get_all_records()

    processed_files = set()
    for row in records:
        if row.get("Обработанный текст") and row.get("Ссылка на видео"):
            processed_files.add(row["Ссылка на видео"].strip())

    return processed_files


def get_video_links():
    """Получение списка ссылок на видео из Google Sheets"""
    client = authorize_google_sheets()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    links = sheet.col_values(1)[1:]  # Пропускаем заголовок
    return [link.strip() for link in links if link.startswith("https://www.loom.com/share/")]


def login_to_loom():
    """Авторизация в Loom"""
    driver.get(LOOM_LOGIN_URL)
    
    email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
    email_input.send_keys(LOOM_EMAIL)
    email_input.send_keys(Keys.RETURN)
    print("✅ Введен Email")
    
    time.sleep(3)
    password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
    password_input.send_keys(LOOM_PASSWORD)
    password_input.send_keys(Keys.RETURN)
    print("✅ Введен пароль и нажата кнопка входа")
    
    wait.until(lambda d: "loom.com/library" in d.current_url or "loom.com/looms/videos" in d.current_url)
    print(f"✅ Успешный вход в Loom. Текущий URL: {driver.current_url}")


def download_transcript(video_url):
    """Загрузка субтитров"""
    driver.get(video_url)
    print(f"🔹 Открыто видео: {video_url}")

    try:
        transcript_button_xpath = "//button[contains(@data-testid, 'sidebar-tab-Transcript')]"
        transcript_button = wait.until(EC.element_to_be_clickable((By.XPATH, transcript_button_xpath)))
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", transcript_button)
        time.sleep(1)
        transcript_button.click()
        print("✅ Вкладка 'Transcript' открыта")
        time.sleep(3)

        download_button_xpath = "//button[contains(@class, 'right-panel-button_rightPanelButton_2DE') and .//span[contains(text(), 'Download')]]"
        download_button = wait.until(EC.element_to_be_clickable((By.XPATH, download_button_xpath)))

        # Если кнопка неактивна, используем JS
        if download_button.is_enabled():
            download_button.click()
        else:
            driver.execute_script("arguments[0].click();", download_button)

        print("✅ Кнопка 'Download' нажата")
        time.sleep(5)  # Ожидание скачивания

    except Exception as e:
        print(f"❌ Ошибка при скачивании субтитров: {e}")


if __name__ == "__main__":
    try:
        processed_transcripts = get_processed_transcripts()
        video_links = get_video_links()
        print(f"🔹 Найдено {len(video_links)} видео в Google Sheets")

        login_to_loom()

        for video in video_links:
            if video in processed_transcripts:
                print(f"⏭️ Пропускаем обработанное видео: {video}")
                continue

            download_transcript(video)

            # Проверяем скачивание файла
            downloaded_files = sorted(
                os.listdir(DOWNLOAD_FOLDER), 
                key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_FOLDER, f)), 
                reverse=True
            )
            print(f"📂 Скачанные файлы: {downloaded_files}")

            if downloaded_files:
                transcript_path = os.path.join(DOWNLOAD_FOLDER, downloaded_files[0])
                print(f"📄 Обнаружен файл: {transcript_path}")

    finally:
        driver.quit()
        print("✅ Браузер закрыт")

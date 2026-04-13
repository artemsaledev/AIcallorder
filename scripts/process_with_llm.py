import os
import time
import gspread
import logging
import subprocess
from oauth2client.service_account import ServiceAccountCredentials

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SHEET_ID = "1MXJmoiCoHvN1y_Q3-rASXOfEVi-uKyhFo8aBzB76328"
SHEET_NAME = "Transcript"
DOWNLOAD_FOLDER = os.getenv("DOWNLOAD_FOLDER", "/app/downloads")
LLM_COMMAND = os.getenv("LOCAL_LLM_COMMAND", "/app/llama.cpp/build/bin/llama-cli")
LLM_MODEL_PATH = os.getenv("LOCAL_LLM_MODEL_PATH", "/app/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "/app/scripts/united-aura-440321-p2-c819703433e8.json",
)

# Оптимальные параметры
MAX_TOKENS = 500  # Уменьшаем размер чанка
PREDICT_TOKENS = 64  # Уменьшаем количество предсказанных токенов
CHUNK_OVERLAP = 25  # Количество пересекающихся токенов между чанками
TIMEOUT_PER_CHUNK = 300  # Увеличиваем таймаут минут

def split_text_into_chunks(text, max_length=MAX_TOKENS, overlap=CHUNK_OVERLAP):
    """Разделяет текст на чанки с перекрытием"""
    words = text.split()
    chunks = []
    chunk = []
    length = 0

    for word in words:
        length += len(word) + 1  # +1 для пробела
        chunk.append(word)

        if length >= max_length - overlap:
            chunks.append(" ".join(chunk))
            chunk = chunk[-overlap:]  # Перекрытие
            length = sum(len(w) + 1 for w in chunk)

    if chunk:
        chunks.append(" ".join(chunk))

    return chunks

def authorize_google_sheets():
    """Авторизация в Google Sheets"""
    logging.info("🔑 Авторизация в Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SERVICE_ACCOUNT_JSON, scope)
    client = gspread.authorize(creds)
    logging.info("✅ Успешная авторизация в Google Sheets")
    return client

def get_unprocessed_transcript():
    """Получает первый не обработанный файл из папки загрузок"""
    logging.info("📂 Поиск необработанных транскрипций в директории...")
    client = authorize_google_sheets()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    processed_transcripts = {row[1] for row in sheet.get_all_values() if len(row) > 2 and row[2]}

    files = sorted(os.listdir(DOWNLOAD_FOLDER), key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_FOLDER, f)), reverse=True)
    for file in files:
        transcript_path = os.path.join(DOWNLOAD_FOLDER, file)
        if file not in processed_transcripts:
            logging.info(f"📄 Найдена новая транскрипция для обработки: {transcript_path}")
            return transcript_path
    logging.warning("⚠️ Все файлы уже обработаны.")
    return None

def process_transcript_with_llm(transcript_path):
    """Обрабатывает текст через LLM"""
    logging.info(f"🤖 Обработка текста через LLM: {transcript_path}")

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_content = f.read().strip()
    except Exception as e:
        logging.error(f"❌ Ошибка при чтении файла {transcript_path}: {e}")
        return None

    if not transcript_content:
        logging.warning(f"⚠️ Файл {transcript_path} пуст, пропускаем обработку.")
        return None

    chunks = split_text_into_chunks(transcript_content, MAX_TOKENS)
    improved_text = ""

    for index, chunk in enumerate(chunks):
        logging.info(f"📄 Обработка чанка {index + 1}/{len(chunks)}...")
        command = [
            LLM_COMMAND, "-m", LLM_MODEL_PATH,
            "--prompt", chunk,
            "--n-predict", str(PREDICT_TOKENS),
            "--temp", "0.8", "--top_k", "40",
            "--log-disable"
        ]
        start_time = time.time()

        try:
            logging.info(f"🔹 Запуск команды: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_PER_CHUNK)
            output = result.stdout.strip()
            error_output = result.stderr.strip()

            if error_output:
                logging.error(f"⚠️ Ошибка выполнения LLM: {error_output}")

            logging.info(f"📤 Ответ LLM: {output[:500]}...")  # Выведет первые 500 символов

            if not output:
                logging.error(f"❌ Ошибка: LLM не вернула обработанный текст для {transcript_path}")
                return None

            improved_text += output + "\n\n"
            logging.info(f"✅ Чанк {index + 1} обработан")
        except subprocess.TimeoutExpired:
            logging.error(f"⏳ Ошибка: LLM превысила лимит времени обработки {transcript_path}")
        except Exception as e:
            logging.error(f"❌ Ошибка при выполнении LLM: {e}")

        elapsed_time = time.time() - start_time
        logging.info(f"⏳ Время обработки чанка {index + 1}: {elapsed_time:.2f} секунд")

    logging.info("✅ Обработка завершена")
    return improved_text.strip()

def save_to_google_sheets(transcript_name, improved_text):
    """Сохраняет обработанный текст в Google Sheets"""
    logging.info(f"📤 Сохранение обработанного текста в Google Sheets для файла: {transcript_name}")
    client = authorize_google_sheets()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    try:
        cell = sheet.find(transcript_name)
        if cell:
            sheet.update_cell(cell.row, 3, improved_text)  # 3 - колонка с улучшенной версией
            logging.info(f"✅ Обновлена строка {cell.row} с обработанным текстом")
        else:
            logging.warning(f"⚠️ Файл {transcript_name} не найден в Google Sheets")
    except Exception as e:
        logging.error(f"❌ Ошибка при обновлении Google Sheets: {e}")

if __name__ == "__main__":
    logging.info("🚀 Запуск обработки транскриптов...")
    transcript_path = get_unprocessed_transcript()

    if transcript_path:
        transcript_name = os.path.basename(transcript_path)
        improved_text = process_transcript_with_llm(transcript_path)

        if improved_text:
            save_to_google_sheets(transcript_name, improved_text)
    else:
        logging.warning("⚠️ Нет доступных транскриптов для обработки.")

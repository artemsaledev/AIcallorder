import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build

# 🔐 Доступ к Google Sheets и Google Docs
SHEET_ID = "1MXJmoiCoHvN1y_Q3-rASXOfEVi-uKyhFo8aBzB76328"
SHEET_NAME = "Transcript"
LLM_COMMAND = os.getenv("LOCAL_LLM_COMMAND", "/app/llama.cpp/build/bin/llama-cli")
LLM_MODEL_PATH = os.getenv("LOCAL_LLM_MODEL_PATH", "/app/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "/app/scripts/united-aura-440321-p2-c819703433e8.json",
)

def authorize_google_services():
    """Авторизация в Google Sheets и Google Docs"""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SERVICE_ACCOUNT_JSON, scope)
    return gspread.authorize(creds), creds

def get_unprocessed_transcripts():
    """Получает обработанные транскрипции, у которых еще нет Google Docs"""
    client, _ = authorize_google_services()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    data = sheet.get_all_records()

    return [
        (row["Ссылка"], row["Обработанный текст"]) for row in data
        if row["Обработанный текст"] and not row["Google Docs Ссылка"]
    ]

def generate_summary(text):
    """Генерация саммари через LLM"""
    command = f'{LLM_COMMAND} -m {LLM_MODEL_PATH} --prompt "Сделай краткое саммари текста: {text}"'
    return os.popen(command).read().strip()

def create_google_doc(title, content):
    """Создание Google Docs с саммари"""
    _, creds = authorize_google_services()
    service = build("docs", "v1", credentials=creds)

    doc = service.documents().create(body={"title": title}).execute()
    document_id = doc["documentId"]

    requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
    service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()

    return f"https://docs.google.com/document/d/{document_id}"

def update_google_sheets(video_url, doc_link):
    """Обновление ссылки в Google Sheets"""
    client, _ = authorize_google_services()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    cell = sheet.find(video_url)
    if cell:
        sheet.update_cell(cell.row, 4, doc_link)  # Записываем ссылку в Google Docs
        sheet.update_cell(cell.row, 5, "Готово")  # Меняем статус

if __name__ == "__main__":
    transcripts = get_unprocessed_transcripts()

    for video_url, processed_text in transcripts:
        if processed_text:
            summary_text = generate_summary(processed_text)
            if summary_text:
                doc_link = create_google_doc("Саммари видео", summary_text)
                update_google_sheets(video_url, doc_link)

    print("✅ Саммари успешно добавлены в Google Docs и сохранены в таблице.")

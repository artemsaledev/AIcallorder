import os
import subprocess
import time
import logging

# 📜 Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 🛠 Пути к скриптам внутри контейнера
SCRIPTS = [
    ("Скачивание транскрипций", "python /app/scripts/download_transcripts.py"),
    ("Обработка LLM", "python /app/scripts/process_with_llm.py"),
    ("Генерация итогового отчета", "python /app/scripts/generate_summary.py")
]

def run_command(name, command):
    """Функция запуска команды с логированием"""
    logging.info(f"🚀 Запуск этапа: {name}")
    process = subprocess.run(command, shell=True)

    if process.returncode != 0:
        logging.error(f"❌ Ошибка при выполнении этапа: {name}. Команда: {command}")
        return False
    
    logging.info(f"✅ Завершено: {name}")
    return True

if __name__ == "__main__":
    start_time = time.time()
    
    for name, script in SCRIPTS:
        success = run_command(name, script)
        if not success:
            logging.warning(f"⚠️ Этап '{name}' не выполнен, продолжаем дальше...")

    elapsed_time = round(time.time() - start_time, 2)
    logging.info(f"\n🎉 Пайплайн завершен за {elapsed_time} секунд!")

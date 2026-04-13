# AIcallorder

Сервис для автоматизации обработки встреч, где Loom используется как облачное хранилище видео и источник транскрипций, а AI-пайплайн превращает записи в управленческие и инженерные артефакты:

- резюме встречи;
- техническое задание по итогам обсуждения;
- статус выполнения плана дня;
- остатки технического долга;
- новые бизнес-задачи на оценку;
- ежедневный digest для Telegram-чата команды.

## Что было не так в текущем подходе

Текущий proof of concept в папке `scripts/` полезен как черновик, но он плохо масштабируется:

- ссылки на записи добавляются вручную в Google Sheets;
- транскрипция забирается через Selenium и UI-клики;
- секреты зашиты в код;
- нет единого хранилища состояния обработки;
- пайплайн линейный и трудно расширяется;
- нет разделения между ingestion, AI-обработкой, публикацией и аналитикой.

## Целевая архитектура

### Сценарий, под который проект теперь ориентирован

Основной сценарий:

- встречи записываются в Discord;
- обучающие видео могут быть записаны вне Zoom/Meet/Teams;
- Loom используется как облачное хранилище видео и единая библиотека ссылок;
- transcript может приходить либо из Loom, либо из внешнего STT.

### 1. Источник записи

Предпочтительный поток:

1. Видео после записи попадает в Loom.
2. Collector обнаруживает новое видео в Loom library.
3. Если у видео уже есть transcript, он используется сразу.
4. Если transcript в Loom нет или он недоступен, transcriber строит его из аудио отдельным STT-движком.

Для Discord и обучающих видео это надежнее, чем опираться на Loom AI for Meetings.

### Приоритет транскрипции

Для твоего сценария правильный порядок такой:

1. Для Loom-видео использовать transcript, который уже сгенерировал Loom.
2. Для локальных видео с компьютера использовать локальный `faster-whisper` внутри проекта.
3. Не рассчитывать на бесплатное API-транскрибирование через `ChatGPT Plus`, потому что подписка `Plus` не включает API usage автоматически. OpenAI отдельно пишет, что `API usage is separate and billed independently`. Источник: [What is ChatGPT Plus?](https://help.openai.com/en/articles/6950777-what-is-chatgpt-plus)

### 2. Пайплайн обработки по модулям

Для каждой встречи сервис должен:

1. `collector`
   - ищет новые видео в Loom;
   - умеет переключаться на локальный файл или локальную папку с видео;
   - сохраняет video id, ссылку, название, теги, время обнаружения;
   - для Loom ожидает готовый transcript;
   - для локальной папки подает файлы в local Whisper pipeline.
2. `transcriber`
   - берет transcript из Loom, если он уже готов;
   - для локальных файлов запускает встроенный `faster-whisper`;
   - при необходимости может использовать внешний `LOCAL_WHISPER_COMMAND`;
   - нормализует текст в единый формат.
3. `summarizer`
   - превращает transcript в engineering artifacts;
   - выделяет summary, decisions, action items, tech debt, business requests, blockers;
   - собирает draft ТЗ.
4. `telegram-reporter`
   - формирует digest по одной встрече;
   - формирует aggregated daily digest по нескольким встречам;
   - отправляет это в Telegram-чат.
5. `storage + publishers`
   - сохраняют transcript и artifacts;
   - публикуют их в Google Docs / Google Sheets.

### 3. Рекомендуемая production-схема для Discord + Loom

```text
Discord recording / uploaded video
  -> Loom library
  -> collector
  -> transcriber
     -> transcript from Loom if available
     -> else local Whisper for local files
  -> summarizer
  -> storage
  -> Google Docs / Sheets
  -> telegram-reporter
  -> team chat
```

Ежедневный digest должен агрегировать все встречи за день и строить сообщение в разрезе:

- что завершено;
- что осталось по плану;
- какой технический долг был зафиксирован;
- какие новые запросы пришли от бизнеса;
- что нужно оценить командой;
- какие follow-up решения нужны завтра.

## Что уже добавлено в этот репозиторий

Новый каркас проекта:

- `loom_automation/main.py` — FastAPI-вход для webhooks и ручного запуска;
- `loom_automation/config.py` — конфигурация через переменные окружения;
- `loom_automation/models.py` — модели встреч и AI-артефактов;
- `loom_automation/workflow.py` — orchestration пайплайна;
- `loom_automation/modules/collector.py` — модуль сбора Loom-видео;
- `loom_automation/modules/transcriber.py` — реальный модуль построения transcript через OpenAI STT или local Whisper;
- `loom_automation/modules/summarizer.py` — модуль генерации артефактов;
- `loom_automation/modules/telegram_reporter.py` — модуль Telegram digest;
- `loom_automation/pipelines/discord_loom.py` — специализированный pipeline под Discord + Loom;
- `loom_automation/prompts.py` — шаблоны задач для AI;
- `loom_automation/integrations/` — адаптеры Loom / Google / Telegram / SQLite;
- `.env.example` — безопасная конфигурация вместо секретов в коде.

Старые скрипты оставлены как legacy-слой и могут использоваться как временный fallback.

## Как я бы довел это до полной автоматизации

### Вариант A: правильный production-flow для твоего кейса

Использовать Loom как хранилище видео, а transcript получать по стратегии `Loom if available, external STT otherwise`:

1. Новое видео появляется в Loom.
2. Collector обнаруживает его.
3. Сервис получает transcript из Loom или строит его сам.
4. AI строит structured output.
5. Результаты пишутся в:
   - Google Docs как meeting note / technical brief;
   - Google Sheets как реестр задач и статусов;
   - Telegram как digest.

### Вариант B: переходный этап

Если API/события Loom ограничены:

1. Оставить Selenium только для обнаружения новых Loom-видео и скачивания transcript.
2. Убрать ручное внесение ссылок в Google Sheets.
3. После обработки записывать состояние в SQLite.
4. Позже заменить collector на более стабильный механизм загрузки/обнаружения.

## Критичные улучшения

1. Немедленно вынести все секреты из кода и ротировать уже использованные пароли/ключи.
2. Перестать хранить статус обработки только в Google Sheets.
3. Разделить встречи, AI-артефакты и уведомления на отдельные сущности.
4. Добавить идемпотентность: одна Loom-встреча должна обрабатываться ровно один раз.
5. Добавить стратегию fallback:
   - primary: API / webhook / controlled integration;
   - secondary: Selenium ingestion.
6. Добавить шаблоны разных типов встреч:
   - standup;
   - grooming;
   - planning;
   - technical sync;
   - business intake.

## Локальный запуск

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
uvicorn loom_automation.main:app --reload
```

### Всегда включенный локальный веб-интерфейс на Windows

Если хочешь управлять проектом только через браузер и не запускать сервер руками каждый раз:

1. Запусти фоновый сервер:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1
```

2. Открой форму управления:

```powershell
.\scripts\open_dashboard.cmd
```

3. Останови сервер при необходимости:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_web.ps1
```

Что делает этот режим:
- поднимает `uvicorn` локально на `http://127.0.0.1:8000`;
- пишет PID и runtime-состояние в `data/runtime/web.pid.json`;
- пишет логи в `data/runtime/logs/uvicorn.stdout.log` и `data/runtime/logs/uvicorn.stderr.log`.

Если `Task Scheduler` на этом профиле не дает создать задачу, можно включить автозапуск через папку Startup:

```powershell
.\scripts\install_startup.cmd
```

Этот скрипт создает user-level launcher в папке Windows Startup, и веб-интерфейс будет подниматься после входа в систему без ручного запуска.

Отключить автозапуск:

```powershell
.\scripts\uninstall_startup.cmd
```

### Временная публикация наружу через Cloudflare Tunnel

Если VPS еще нет, можно поднять временный защищенный HTTPS URL к локальному интерфейсу:

1. Убедись, что локальный веб уже запущен:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1
```

2. Подними Quick Tunnel:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_tunnel.ps1
```

3. Посмотри публичный URL:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\show_tunnel_url.ps1
```

4. Останови туннель, если он больше не нужен:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_tunnel.ps1
```

Что важно:
- это временный `trycloudflare.com` URL;
- адрес изменится после нового старта туннеля;
- локальный компьютер должен быть включен;
- это удобно для тестов и временного внешнего доступа, но не заменяет VPS.

### Provider-based LLM

Теперь summarizer работает через явный слой провайдеров:

- `LLM_PROVIDER=local` — использовать локальную модель
- `LLM_PROVIDER=openai` — использовать OpenAI API
- `LLM_PROVIDER=compatible` — использовать OpenAI-compatible API через свой `LLM_BASE_URL`
- `LLM_PROVIDER=auto` — сначала локальная модель, потом облачный API

Новые переменные:

```env
LLM_PROVIDER=auto
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=120
```

Обратная совместимость сохранена:
- если уже настроены `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, они продолжают работать;
- если уже настроен `LOCAL_LLM_COMMAND`, локальный summarizer продолжает работать;
- локальная транскрибация через Whisper остается запасным контуром.

### Локальный LLM для summarizer

Рабочий локальный вариант для structured summary:

1. Установить `Ollama`.
2. Скачать модель `qwen2.5:3b`.
3. Указать в `.env`:

```env
LOCAL_LLM_COMMAND=C:\Users\artem\Downloads\dev-scripts\4. Loom\scripts\run_ollama_qwen.cmd
```

Скрипт [run_ollama_qwen.cmd](C:/Users/artem/Downloads/dev-scripts/4.%20Loom/scripts/run_ollama_qwen.cmd) запускает:

```text
ollama run qwen2.5:3b --format json --nowordwrap --hidethinking
```

Это позволяет `summarizer` получать локальный JSON-ответ без облачного API.

### Целевая production-схема

Для VPS-версии рекомендуется такой режим:

1. `Loom transcript` как основной источник текста для Loom-встреч.
2. `LLM_PROVIDER=openai` или `LLM_PROVIDER=compatible` как основной summarizer.
3. `LOCAL_LLM_COMMAND` и локальный Whisper оставить как fallback.

Важно: `ChatGPT Plus` не заменяет API-биллинг для внешнего сервиса. Для production-интеграции нужен отдельный API-провайдер. Источник: [What is ChatGPT Plus?](https://help.openai.com/en/articles/6950777-chatgpt-plus)

## Фильтрация Loom по названию

Если в одном аккаунте Loom работают разные сотрудники и не все видео нужно обрабатывать, включай фильтрацию по словам в названии:

```env
LOOM_TITLE_INCLUDE_KEYWORDS=оплат,заказ,доставк,ina
LOOM_TITLE_EXCLUDE_KEYWORDS=обучение,tutorial,demo
```

Логика:
- если `LOOM_TITLE_INCLUDE_KEYWORDS` заполнен, будут взяты только видео, где в названии есть хотя бы одно из этих слов;
- если `LOOM_TITLE_EXCLUDE_KEYWORDS` заполнен, такие видео будут пропущены;
- фильтры применяются к `Loom auto import` и scheduler-импорту.

## Prompt routing по названию видео

Для связи названия Loom-видео с целевыми prompt-профилями используется файл:

[prompt_routes.json](C:/Users/artem/Downloads/dev-scripts/4.%20Loom/promts/prompt_routes.json)

Пример маршрута:

```json
{
  "name": "payments-and-orders",
  "enabled": true,
  "title_include_keywords": ["оплат", "заказ", "доставк", "ina"],
  "title_exclude_keywords": ["обучение", "tutorial", "demo"],
  "prompt_path": "promts/promts_transcription.txt"
}
```

Это значит:
- если в названии Loom-видео встречаются слова из `title_include_keywords`;
- и не встречаются слова из `title_exclude_keywords`;
- перед summarizer будет применен внешний prompt из файла [promts_transcription.txt](C:/Users/artem/Downloads/dev-scripts/4.%20Loom/promts/promts_transcription.txt), который чистит и нормализует исходную транскрипцию.

## Внешний prompt для обработки транскрипции

Твой prompt уже подключен как реальный preprocessing-слой:

[promts_transcription.txt](C:/Users/artem/Downloads/dev-scripts/4.%20Loom/promts/promts_transcription.txt)

Теперь pipeline для подходящих Loom-видео работает так:

1. Получает transcript из Loom.
2. Прогоняет transcript через внешний prompt очистки.
3. Передает уже очищенный текст в основной summarizer.

Если нужно временно отключить этот шаг:

```env
TRANSCRIPT_PREPROCESS_ENABLED=false
```

Примеры эндпоинтов:

- `GET /` — локальный интерфейс выбора источника;
- `POST /webhooks/loom`
- `POST /meetings/process`
- `POST /meetings/process-folder`
- `POST /reports/daily`
- `GET /scheduler/status`
- `POST /scheduler/run-local-folder`
- `POST /scheduler/run-loom-import`
- `GET /health`

### Локальный интерфейс запуска

После старта сервиса открой в браузере:

```text
http://127.0.0.1:8000/
```

Там можно переключать источник обработки:

- `Loom transcript`
- `Loom auto import`
- `Local file`
- `Local folder`

И указывать на каждый запуск, что именно нужно обработать сейчас.

Для автоматического импорта новой порции Loom-транскрипций также доступен endpoint:

```json
POST /loom/import-latest
{
  "limit": 5,
  "meeting_type": "discord-sync"
}
```

Collector логинится в Loom library, ищет новые share-ссылки, пытается открыть transcript и импортирует только те элементы, которых еще нет в локальной базе SQLite.

Пример обработки папки с локальными видео:

```json
POST /meetings/process-folder
{
  "folder_path": "C:\\Users\\artem\\Videos\\discord-recordings",
  "meeting_type": "discord-sync"
}
```

Пример обработки Loom-видео с уже готовой транскрипцией:

```json
POST /meetings/process
{
  "collector_source": "loom",
  "loom_url": "https://www.loom.com/share/abc123",
  "title": "Discord architecture sync",
  "meeting_type": "discord-sync",
  "transcript_text": "текст транскрипции из Loom"
}
```

## Следующий практический шаг

Я бы делал внедрение в таком порядке:

1. Определить способ обнаружения новых видео в Loom library:
   - Selenium collector;
   - watched folder + auto upload;
   - ручная передача Loom links в API как временный режим;
   - локальная папка с видео как отдельный источник.
2. Подключить local faster-whisper и проверить обработку папки.
3. Подключить реальный AI backend:
   - OpenAI API;
   - локальная LLM;
   - гибрид.
4. Подключить Google Docs и Telegram.
5. После этого заменить legacy scripts на единый сервисный pipeline.

## Google Workspace setup

Публикация в Google Docs и Google Sheets теперь реализована в коде через
[google_workspace.py](C:/Users/artem/Downloads/dev-scripts/4.%20Loom/loom_automation/integrations/google_workspace.py).

Чтобы она реально писала данные в твой Google Workspace, нужно:

1. Расшарить целевую Google Docs папку и Google Sheet на service account:

```text
google-sheets-integration@united-aura-440321-p2.iam.gserviceaccount.com
```

2. Указать в `.env`:

```env
GOOGLE_DOCS_FOLDER_ID=...
GOOGLE_SHEETS_ID=...
GOOGLE_SHEETS_WORKSHEET=Transcript
```

После этого pipeline сможет:
- создавать или обновлять отдельный Google Doc по встрече;
- добавлять или обновлять строку в Google Sheet по `loom_video_id`.

## Scheduler

Встроенный scheduler теперь может:
- периодически обрабатывать локальную папку с видео;
- периодически импортировать новые Loom transcript;
- хранить runtime-настройки между рестартами сервиса в `data/scheduler_settings.json`;
- управляться из веб-интерфейса без ручного редактирования `.env`.
- работать без ручного открытия UI.

Настройки в `.env`:

```env
SCHEDULER_ENABLED=true
SCHEDULER_MEETING_TYPE=discord-sync
SCHEDULER_LOCAL_FOLDER_ENABLED=true
LOCAL_VIDEO_FOLDER=C:\Users\artem\OneDrive\Документы\Zoom
SCHEDULER_LOCAL_FOLDER_MINUTES=30
SCHEDULER_LOOM_ENABLED=true
SCHEDULER_LOOM_MINUTES=30
SCHEDULER_LOOM_LIMIT=3
SCHEDULER_ACTIVE_FROM=08:00
SCHEDULER_ACTIVE_TO=21:00
SCHEDULER_ACTIVE_WEEKDAYS=mon,tue,wed,thu,fri
```

Диагностика:
- `GET /scheduler/status` — текущее состояние задач и время следующего запуска
- `POST /scheduler/run-local-folder` — запустить локальную папку вне очереди
- `POST /scheduler/run-loom-import` — запустить Loom import вне очереди

По умолчанию локальная расшифровка настроена на `LOCAL_WHISPER_MODEL=medium`, а после транскрибации применяется нормализация частых доменных терминов вроде `Bitrix`, `1С`, `CRM`, `артикул`.

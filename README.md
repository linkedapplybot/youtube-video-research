# YouTube Video Research Pipeline

Автоматический пайплайн: исследование темы через YouTube → аналитический отчёт → готовое видео с AI-картинками, озвучкой и субтитрами.

## Что на выходе

За один запуск (~45 минут) пайплайн:
- Находит 500 свежих YouTube-видео по теме
- Скачивает субтитры и метаданные
- Загружает всё в NotebookLM и генерирует отчёт + сценарий
- Рисует картинки через Gemini (24 шт, 16:9)
- Озвучивает сценарий через Gemini TTS
- Собирает видео через ffmpeg (Ken Burns + crossfade + субтитры)

**Пример результата:** видео 10–15 минут, ~150 МБ, с русскими субтитрами.

## Структура папки

```
youtube-video-research/
├── run.py                  ← главный оркестратор
├── step1_keywords.py       ← генерация ключевых слов (Gemini)
├── step2_search.py         ← поиск видео (YouTube reversed API)
├── step3_download.py       ← скачивание субтитров/метаданных/комментариев (yt-dlp)
├── step4_merge.py          ← объединение данных в текстовые файлы
├── step5_notebooklm.py     ← NotebookLM: отчёт + сценарий
├── step6_parse_script.py   ← парсинг сценария → segments.json (Gemini)
├── step7_media.py          ← генерация картинок + TTS озвучка (Gemini)
├── step8_assemble.py       ← сборка видео (ffmpeg)
├── step9_subtitles.py      ← субтитры: SRT + burn-in (ffmpeg)
├── config.json             ← все настройки и API-ключи
└── README.md

# Артефакты (создаются при запуске):
├── {Тема}_research/        ← work_dir: субтитры, метаданные, чанки
└── {Тема}_2026/            ← output_dir: видео, отчёт, картинки, аудио
```

## Зависимости

### Системные утилиты
```bash
brew install yt-dlp ffmpeg
```

### Python-пакеты
Все зависимости перечислены в `requirements.txt`:
```bash
pip3 install -r requirements.txt
```

### NotebookLM CLI
```bash
uv tool install notebooklm-mcp-cli
```

### YouTube API Reverser
Папка `~/PycharmProjects/youtube_api_reverser/` с файлом `youtube_api_config.json`.
Путь настраивается в `config.json` → `youtube_api_reverser_path`.

## Настройка config.json

```json
{
  "gemini_api_key": "AIzaSy...",           // Google AI Studio: aistudio.google.com
  "nlm_bin": "~/.local/bin/nlm",           // путь к nlm CLI
  "youtube_api_reverser_path": "~/PycharmProjects/youtube_api_reverser",
  "work_base_dir": "~/PycharmProjects/youtube-video-research",  // промежуточные файлы
  "output_base_dir": "~/PycharmProjects/youtube-video-research", // готовые артефакты
  "default_voice": "Fenrir",               // голос TTS (Fenrir, Kore, Charon, Aoede...)
  "default_langs": ["en", "ru"],           // языки поиска по умолчанию
  "default_n_videos": 500,                 // сколько видео искать
  "subtitle_font_size": 14,
  "video_fps": 25,
  "video_width": 1920,
  "video_height": 1080,
  "video_crf": 21,                         // качество видео (18=лучше, 28=хуже)
  "download_threads": 10,
  "comment_threads": 5,
  "download_comments": false,              // true — включить скачивание комментариев (YouTube может блокировать)
  "proxies_file": "~/path/to/proxies.txt"  // файл со списком прокси (по одному на строку), убери если не нужно
}
```

### Gemini API Key
1. Открыть [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Создать ключ → вставить в `config.json` → `gemini_api_key`
3. Бесплатный тариф покрывает весь пайплайн (~$0 при использовании free tier)

## Прокси

Для обхода блокировок YouTube укажи список прокси в `proxies.txt` (один прокси на строку):

```
http://user:pass@host1:port
http://user:pass@host2:port
```

Каждый поток yt-dlp получает свой прокси по round-robin. При 10 потоках используются прокси 0–9, при следующем запуске снова с начала. Субтитры и метаданные используют разные прокси (субтитры: 0–9, метаданные: 10–19).

Если `proxies_file` не указан или файл не найден — загрузка идёт без прокси.

## Подключение NotebookLM

NotebookLM использует Google-аккаунт через браузерные cookies.

### Первичная авторизация
```bash
~/.local/bin/nlm login
# Откроется Chrome, нужно войти в Google-аккаунт
# Cookies сохраняются в ~/.notebooklm-mcp-cli/profiles/default/cookies.json
```

### Проверка статуса
```bash
~/.local/bin/nlm login --check
# ✓ Authentication valid!
# Account: your@gmail.com
# Notebooks found: 42
```

### Обновление сессии
Cookies живут ~1 неделю. Когда истекут — повторить `nlm login`.

```bash
# Принудительно обновить (сменить аккаунт):
~/.local/bin/nlm login --force --clear
```

### Где хранится сессия
```
~/.notebooklm-mcp-cli/
└── profiles/
    └── default/
        ├── cookies.json    ← Google session cookies
        └── metadata.json   ← аккаунт, дата последней валидации
```

## Запуск

### Базовый запуск
```bash
cd ~/PycharmProjects/youtube-video-research
python3 run.py --topic "Кайтсерфинг в ЮАР"
```

### С параметрами
```bash
python3 run.py \
  --topic "Сёрфинг на Бали" \
  --langs en,ru,id \
  --n-videos 500 \
  --voice Fenrir
```

### Возобновить с нужного шага
Если пайплайн упал на шаге 7 — можно продолжить с него, не переделывая предыдущие:
```bash
python3 run.py --topic "Сёрфинг на Бали" --from-step 7
```

### Параметры запуска
| Параметр | По умолчанию | Описание |
|---|---|---|
| `--topic` | обязательный | Тема исследования |
| `--langs` | `en,ru` | Языки поиска через запятую |
| `--n-videos` | `500` | Сколько видео найти |
| `--voice` | `Fenrir` | Голос TTS |
| `--from-step` | `1` | Начать с шага N (пропустить предыдущие) |
| `--config` | `config.json` | Путь к конфигу |

### Доступные голоса TTS (Gemini)
`Fenrir`, `Kore`, `Charon`, `Aoede`, `Puck`, `Leda`, `Orus`, `Zephyr`

## Как работает каждый шаг

| Шаг | Что делает | Входные данные | Выходные данные |
|---|---|---|---|
| 1 | Генерирует 60–80 ключевых слов на указанных языках | тема | `keywords.txt` |
| 2 | Ищет свежие видео через YouTube reversed API | `keywords.txt` | `video_urls.txt`, `videos.csv` |
| 3 | Скачивает субтитры (10 потоков) + метаданные (10 потоков) параллельно | `video_urls.txt` | `subtitles/`, `metadata/` |
| 4 | Объединяет данные в текстовые файлы ≤500 КБ для NotebookLM | `subtitles/`, `metadata/` | `{slug}_data_part_NN.txt` |
| 5 | Создаёт блокнот NLM, загружает файлы, генерирует отчёт и сценарий | `data_part_*.txt` | `report.md`, `video_script.md` |
| 6 | Парсит сценарий через Gemini → структурированный JSON | `video_script.md` | `segments.json` |
| 7 | Параллельно генерирует 3 картинки/сегмент + TTS аудио | `segments.json` | `images/*.png`, `audio/*.wav` |
| 8 | Собирает видео: Ken Burns эффект + crossfade + concat | `images/`, `audio/` | `video_raw.mp4` |
| 9 | Создаёт SRT субтитры и вжигает в видео | `video_raw.mp4`, `segments.json` | `subtitles.srt`, `video_subtitled.mp4` |

### Чекпоинты
Каждый шаг проверяет наличие своих выходных файлов перед запуском. Если файлы уже есть — шаг пропускается. Это позволяет безопасно перезапускать пайплайн после ошибок.

## Стоимость

| Сервис | Использование | Стоимость |
|---|---|---|
| Gemini API | Keywords + script parsing + 24 images + 8 TTS | **~$0** (free tier) |
| NotebookLM | 1 notebook + 2 artifacts | **$0** (бесплатно) |
| YouTube | Поиск + субтитры через yt-dlp | **$0** |

Итого: **бесплатно** при использовании Gemini free tier (лимит: 1500 запросов/день).

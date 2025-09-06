# VideoDownloader — загрузчик видео на yt-dlp

Графический интерфейс для скачивания видео с **YouTube, RuTube, Яндекс Диска)** и других сайтов.  
Построен на [yt-dlp](https://github.com/yt-dlp/yt-dlp) и `tkinter` (идет вместе с Python).

---

## Возможности

- Поддержка различных видеохостингов (YouTube, RuTube, VK, Twitch, Vimeo и т.д.).  
- Скачивание по одной ссылке за раз.  
- Автоматическое преобразование в **MP4**.  
- Возможность указать имя файла (расширение `.mp4` добавляется автоматически).  
- Прогрессбар и лог загрузки.  
- Простое GUI.  

---

## Установка

### 1. Клонировать репозиторий
```bash
git clone https://github.com/janesmelkova/VideoDownloader
cd VideoDownloader
```

### 2. Создать виртуальное окружение
```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows
```

### 3. Установить зависимости
```bash
pip install -r requirements.txt
```

### 4. Установить FFmpeg
```bash
pip install -r requirements.txt
```
yt-dlp использует ffmpeg для слияния аудио/видео и конвертации.

macOS: brew install ffmpeg

Linux (Debian/Ubuntu): sudo apt install ffmpeg

Windows: [скачать сборку](https://www.gyan.dev/ffmpeg/builds/) и прописать путь в PATH.

### ЗАПУСК
```bash
python fetch_media.py
```

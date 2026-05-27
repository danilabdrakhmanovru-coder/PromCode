FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_USE_MOCK=true \
    MPLCONFIGDIR=/tmp/matplotlib

# Render/Docker запускается на Linux, где по умолчанию может не быть шрифтов с кириллицей.
# DejaVu и Liberation нужны для PNG-макетов/рендеров, чтобы русский текст не превращался в квадраты.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        fonts-dejavu-extra \
        fonts-liberation \
        fontconfig && \
    fc-cache -f -v && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY prompts ./prompts
COPY .env.example ./.env.example

EXPOSE 8000

CMD sh -c "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"

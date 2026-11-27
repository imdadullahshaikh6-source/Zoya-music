# Zoya Music Bot — Docker image
# Python 3.12 (3.10 wali deprecation warning yahin khatam). ffmpeg + node + aria2 image me hi.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Kolkata

# System packages: ffmpeg (stream), nodejs (yt-dlp JS challenge solver), aria2 (fast video download),
# build-essential (TgCrypto etc. agar wheel na mile), git/curl/ca-certificates, tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg nodejs aria2 git curl ca-certificates tzdata build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pehle sirf requirements -> code badalne pe pip layer cache se aati hai (rebuild tez)
COPY requirements.txt .
RUN pip install -U pip && pip install -r requirements.txt

COPY . .
RUN chmod +x /app/docker-entrypoint.sh

# Persist hone wali cheezein (compose me volumes): downloads, cache, data (cookies + session)
VOLUME ["/app/downloads", "/app/cache", "/data"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]

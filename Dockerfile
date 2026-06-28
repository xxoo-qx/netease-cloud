FROM ghcr.io/3899/ncmm:latest AS ncmm-upstream


FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app/netease-cloud-main

COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . ./
COPY --from=ncmm-upstream /usr/local/bin/ncmm /usr/local/bin/ncmm
RUN mkdir -p /opt/ncmm /data/user_data /data/ncmm-home

ENV HOST=0.0.0.0 \
    PORT=8080 \
    USER_DATA_DIR=/data/user_data \
    NCMM_PROJECT_DIR=/opt/ncmm \
    NCMM_BIN=/usr/local/bin/ncmm \
    NCMM_HOME_DIR=/data/ncmm-home

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os, sys, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8080\")}/', timeout=5); sys.exit(0)"

CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8080}"]
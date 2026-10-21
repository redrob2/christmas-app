FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_PATH=/app/data \
    PUID=99 \
    PGID=100

WORKDIR /app

# tzdata: TZ applies to countdowns and reminder times
# tini:   runs as PID 1, passes stop signals to the web server and scheduler
RUN apt-get update && apt-get install -y --no-install-recommends tzdata tini \
    && rm -rf /var/lib/apt/lists/*

# psycopg2-binary and Pillow ship prebuilt wheels, so no compiler is needed
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/docker/entrypoint.sh

# Database file, photos and generated keys (map this to appdata)
VOLUME ["/app/data"]
EXPOSE 8123

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8123/healthz', timeout=5).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/app/docker/entrypoint.sh"]

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Time zone data so TZ in .env applies (countdowns, reminder times)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata     && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (psycopg2-binary and Pillow ship prebuilt wheels,
# so no compiler or libpq headers are needed)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directories for data persistence
RUN mkdir -p /app/data/assignments /app/data/uploads/profiles /app/data/uploads/items

# Expose port
EXPOSE 8123

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8123/healthz', timeout=5).status == 200 else 1)"

# Run with gunicorn
#  --preload       create tables / default admin once, before workers fork
#  gthread workers keep the site responsive while an AI request is running
#  --timeout 330   AI photo generation can take up to ~5 minutes (primary + fallback model)
CMD ["gunicorn", "--bind", "0.0.0.0:8123", "--preload", \
     "--workers", "2", "--worker-class", "gthread", "--threads", "4", \
     "--timeout", "330", "--graceful-timeout", "30", \
     "--access-logfile", "-", "run:app"]

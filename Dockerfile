# Asclepius API — multi-tenant backend for the iOS app.
#
#   docker build -t asclepius .
#   docker run -p 8080:8080 --env-file .env -v asclepius-data:/app/data asclepius
#
# Health data lives in /app/data (one SQLite DB per user) — mount a volume.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY scripts/ scripts/

ENV PORT=8080 \
    ASCLEPIUS_MULTI_TENANT=1 \
    ASCLEPIUS_DB=/app/data/health.db

EXPOSE 8080

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]

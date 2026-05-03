FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY dataset/ ./dataset/

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    LOG_LEVEL=INFO

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/v1/healthz')"

CMD ["uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

FROM python:3.11-slim

WORKDIR /app

# System deps: libpq for psycopg2, gcc for building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root for security
RUN adduser --disabled-password --no-create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Override UVICORN_WORKERS (default 2) via docker run -e or docker-compose environment
ENV UVICORN_WORKERS=2

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]

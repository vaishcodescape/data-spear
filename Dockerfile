FROM python:3.11-slim

WORKDIR /app

# libpq for psycopg2, gcc for any source builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install the package and its dependencies from pyproject.toml. Copying only the
# metadata + package first keeps the dependency layer cached across source edits.
COPY pyproject.toml README.md ./
COPY data_spear ./data_spear
RUN pip install --no-cache-dir .

# Run as non-root for security
RUN adduser --disabled-password --no-create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# The agent holds the active database connection in per-process state, so the
# server must run single-worker (a /connect on one worker wouldn't be visible to
# the others). Override with -e UVICORN_WORKERS only if you know the requests are
# independently connected.
ENV UVICORN_WORKERS=1

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["sh", "-c", "uvicorn data_spear.api.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]

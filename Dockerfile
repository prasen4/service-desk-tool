FROM python:3.12-slim

# WeasyPrint system dependencies for PDF rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev \
    shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY config/ config/
COPY src/ src/
# Include the Postgres driver so DATABASE_URL can switch backends without
# rebuilding; SQLite remains the default when DATABASE_URL is empty.
RUN pip install --no-cache-dir ".[postgres]"

# Run as a non-root user and let it own the data volume.
RUN useradd --system --create-home --home-dir /home/techdesk techdesk \
    && mkdir -p /data \
    && chown -R techdesk:techdesk /data
USER techdesk

ENV TECH_DESK_DATA_DIR=/data \
    TECH_DESK_HOST=0.0.0.0 \
    TECH_DESK_PORT=8080 \
    ENV=production \
    PYTHONUNBUFFERED=1

VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://localhost:8080/api/health').status==200 else sys.exit(1)"

# Single process only: the job registry and scheduler live in-process.
CMD ["uvicorn", "tech_desk.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

# syntax=docker/dockerfile:1
# One Dockerfile, three small images:  --target pipeline | api | dashboard
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    GREENSPACE_DATA_DIR=/data GREENSPACE_CONFIG=/app/configs/barcelona.yaml
WORKDIR /app
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app:app /data
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs

# --- batch job: fetch APIs, build the green layer, score, validate, publish -------------------------------------
FROM base AS pipeline
RUN pip install ".[pipeline]"
USER app
VOLUME /data
CMD ["greenspace", "run"]

# --- read-only REST API (no geo libraries -> small image) -------------------------------------------------------
FROM base AS api
RUN pip install ".[api]"
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "greenspace.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

# --- dashboard (talks to the API only) ---------------------------------------------------------------------------
FROM base AS dashboard
RUN pip install ".[dashboard]"
ENV API_URL=http://api:8000
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"
CMD ["streamlit", "run", "src/greenspace/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
FROM base AS app

COPY . .

# Non-root user
RUN useradd -r -u 1001 -m snipe && chown -R snipe:snipe /app
USER snipe

# ── Bot service ───────────────────────────────────────────────────────────────
FROM app AS bot
CMD ["python", "main.py"]

# ── API service ───────────────────────────────────────────────────────────────
FROM app AS api
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Worker (background tasks only) ───────────────────────────────────────────
FROM app AS worker
CMD ["python", "-c", "import asyncio; from src.workers.scheduler import BackgroundScheduler; from src.core.price_engine import PriceEngine; s = BackgroundScheduler(PriceEngine()); asyncio.run(s.start()); asyncio.get_event_loop().run_forever()"]

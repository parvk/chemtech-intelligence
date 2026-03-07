FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for RDKit, AiZynthFinder, and ONNX Runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxrender1 \
    libxext6 \
    libgomp1 \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching)
# Stub app/ so hatchling can resolve the package without the full source
COPY pyproject.toml .
RUN mkdir -p app && touch app/__init__.py
RUN pip install --no-cache-dir -e . && pip uninstall -y numba || true

# Now copy the full source (invalidates cache only when source changes)
COPY . .
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chmod +x /app/scripts/download_models.sh

# ─── Development stage ────────────────────────────────────────────────────────
FROM base AS development

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8001
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

# ─── Production stage ─────────────────────────────────────────────────────────
FROM base AS production

RUN addgroup --system chemflow && adduser --system --ingroup chemflow chemflow
RUN chown -R chemflow:chemflow /app && chmod +x /entrypoint.sh
USER chemflow

EXPOSE 8001
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2", "--loop", "uvloop", "--http", "httptools"]

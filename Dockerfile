FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
ENV PYTHONPATH=/app/src
RUN uv sync --frozen --no-dev
COPY src/backend/ ./src/backend/
COPY src/frontend/ ./src/frontend/

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

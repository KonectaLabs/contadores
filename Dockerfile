FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app/src/frontend
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/index.html src/frontend/tsconfig.json src/frontend/vite.config.ts ./
COPY src/frontend/public ./public
COPY src/frontend/src ./src
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-liberation git nodejs npm \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g @openai/codex@0.125.0
COPY pyproject.toml uv.lock ./
ENV PYTHONPATH=/app/src
ENV CODEX_HOME=/app/data/codex-home
ENV CODEX_BIN=/usr/local/bin/codex
RUN uv sync --frozen --no-dev
COPY src/backend/ ./src/backend/
COPY .codex/skills/ ./.codex/skills/
COPY --from=frontend-builder /app/src/frontend/dist ./src/frontend/dist

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

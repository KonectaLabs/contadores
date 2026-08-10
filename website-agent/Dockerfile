FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY backend backend
RUN uv sync --frozen

COPY frontend frontend
COPY tests tests

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "--no-sync", "fastapi", "run", "backend/main.py", "--host", "0.0.0.0", "--port", "8000"]

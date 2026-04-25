FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
COPY src/bot/pyproject.toml src/bot/uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/bot/ ./

EXPOSE 8100
CMD ["uv", "run", "fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8100"]

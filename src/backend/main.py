from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    print(
        "contadores runtime",
        {
            "enabled": settings.enabled,
            "source_mode": settings.source_mode,
            "ready": not settings.readiness_issues(),
        },
    )
    yield


app = FastAPI(
    title="Contadores Backend",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "contadores-backend"}


@app.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "enabled": settings.enabled,
        "source_mode": settings.source_mode,
        "ready": not settings.readiness_issues(),
    }


@app.get("/api/runtime")
async def runtime() -> dict[str, object]:
    return get_settings().public_dict()

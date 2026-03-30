from __future__ import annotations
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.services.ngrok_service import get_ngrok_url, start_ngrok, stop_ngrok

settings = get_settings()
logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_ngrok()
    yield
    await stop_ngrok()


app = FastAPI(title="AgentMarket API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


@app.get("/health", tags=["system"])
async def health():
    return {
        "status":      "ok",
        "environment": settings.environment,
        "chain_id":    settings.chain_id,
        "identity_registry": settings.identity_registry_address or "not_deployed",
        "ngrok": get_ngrok_url(),
    }
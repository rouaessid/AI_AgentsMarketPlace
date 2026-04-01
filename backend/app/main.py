from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.db.database import init_db
from app.services.ngrok_service import (
    get_ngrok_url, get_all_endpoints,
    start_ngrok, stop_ngrok,
)

settings = get_settings()
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialiser DB
    init_db()
    # 2. Charger agents depuis DB + IPFS
    from app.services.agent_service import restore_from_db
    await restore_from_db()
    # 3. Démarrer tunnel
    await start_ngrok()
    yield
    await stop_ngrok()


app = FastAPI(
    title="AgentMarket API",
    version="0.1.0",
    description="## AgentMarket — Decentralized AI Agent Marketplace\n### Phase 1",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

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
        "contracts": {
            "identity_registry": settings.identity_registry_address or "not_deployed",
        },
        "tunnel": {
            "active":   get_ngrok_url() is not None,
            "base_url": get_ngrok_url(),
        },
        "ipfs": {
            "backend": "pinata" if settings.use_ipfs else "local",
        },
    }


@app.get("/tunnel", tags=["system"])
async def tunnel_info():
    url       = get_ngrok_url()
    endpoints = get_all_endpoints()
    return {
        "tunnel_url": url,
        "active":     url is not None,
        "endpoints":  endpoints,
    }
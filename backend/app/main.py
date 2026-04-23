from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
async def lifespan(_app: FastAPI):
    # 1. Créer toutes les tables (SQLAlchemy — safe si elles existent déjà)
    init_db()

    # 2. Charger agents depuis DB en mémoire (identity + telemetry séparés)
    from app.services.agent_service import restore_from_db
    await restore_from_db()

    # 3. Reset orphaned validations (backend was killed mid-run)
    from app.db.access_repo import reset_stale_validations
    stale = reset_stale_validations()
    if stale:
        logger.warning("Reset %d stale validation session(s) to 'awaiting_run'", stale)

    # 4. Démarrer le blockchain indexer en tâche de fond
    from app.services.blockchain_indexer import BlockchainIndexer
    indexer = BlockchainIndexer()
    indexer_task = asyncio.create_task(indexer.start())
    logger.info("BlockchainIndexer démarré en arrière-plan")

    # 5. Démarrer tunnel
    await start_ngrok()

    yield

    # Arrêt propre — gather absorbe le CancelledError sans le perdre
    indexer_task.cancel()
    await asyncio.gather(indexer_task, return_exceptions=True)
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


@app.get("/ipfs/{cid}", tags=["ipfs"])
async def serve_local_ipfs(cid: str):
    """Serve local IPFS files so judge containers can fetch traces via host.docker.internal."""
    base = Path(settings.storage_path) / "ipfs_local"
    f = base / f"{cid}.json"
    if not f.exists():
        raise HTTPException(404, detail=f"CID {cid} not found locally")
    import json
    return JSONResponse(json.loads(f.read_text(encoding="utf-8")))


@app.get("/tunnel", tags=["system"])
async def tunnel_info():
    url       = get_ngrok_url()
    endpoints = get_all_endpoints()
    return {
        "tunnel_url": url,
        "active":     url is not None,
        "endpoints":  endpoints,
    }
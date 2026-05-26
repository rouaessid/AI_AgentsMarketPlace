from __future__ import annotations
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
# Import FlagEmbedding before the rest of the app. On Windows, importing it
# after sklearn/pandas/pyarrow have been pulled in can crash Python natively.
from FlagEmbedding import FlagModel  # noqa: F401

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.db.database import init_db
from app.services.ngrok_service import (
    get_ngrok_url, get_all_endpoints,
    start_ngrok, stop_ngrok,
    start_watchdog, stop_watchdog,
)

settings = get_settings()
_log_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.DEBUG if settings.debug else logging.INFO)
# Console handler
_ch = logging.StreamHandler()
_ch.setFormatter(_log_fmt)
_root.addHandler(_ch)
# File handler — toujours actif, indépendant du terminal
try:
    Path("C:/tmp").mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler("C:/tmp/backend.log", encoding="utf-8")
    _fh.setFormatter(_log_fmt)
    _root.addHandler(_fh)
except OSError as _e:
    logging.getLogger(__name__).warning("File logging disabled: %s", _e)
# Silence very verbose third-party loggers
for _noisy in ("web3", "urllib3", "httpcore", "httpx", "sentence_transformers",
               "datasets", "huggingface_hub", "filelock", "transformers",
               "app.services.ngrok_service"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 1. Créer toutes les tables (SQLAlchemy — safe si elles existent déjà)
    init_db()

    # 2. Charger agents depuis DB en mémoire (identity + telemetry séparés)
    from app.services.agent_service import restore_from_db
    await restore_from_db()

    # 3. Reset orphaned validations and pipeline tasks (backend was killed mid-run)
    from app.db.access_repo import reset_stale_validations
    from app.db.pipeline_repo import reset_stale_pipeline_tasks
    try:
        stale = reset_stale_validations()
        if stale:
            logger.warning("Reset %d stale validation session(s) to 'awaiting_run'", stale)
    except Exception as _e:
        logger.warning("Could not reset stale validation sessions: %s", _e)
    try:
        stale_tasks = reset_stale_pipeline_tasks()
        if stale_tasks:
            logger.warning("Reset %d stale pipeline task(s) to 'failed'", stale_tasks)
    except Exception as _e:
        logger.warning("Could not reset stale pipeline task(s): %s", _e)

    # 4. (blockchain_indexer removed — The Graph now indexes all on-chain events)

    # 5. Backfill embeddings for agents registered before embedding support
    async def _backfill_embeddings():
        import asyncio as _aio
        from app.db.database import AgentEmbedding, get_session
        from app.services.matching_service import embed_agent_capabilities
        from app.services.agent_service import get_agent_from_cache, _fetch_ipfs_manifest
        import json as _json
        with get_session() as _s:
            rows = (
                _s.query(AgentEmbedding)
                .filter(AgentEmbedding.capability_embedding.is_(None))
                .filter(AgentEmbedding.ipfs_cid.isnot(None))
                .all()
            )
            rows = [{"agent_id": r.agent_id, "ipfs_cid": r.ipfs_cid} for r in rows]
        if not rows:
            return
        logger.info("Backfilling embeddings for %d agent(s)…", len(rows))
        loop = _aio.get_event_loop()
        for row in rows:
            try:
                cached = get_agent_from_cache(row["agent_id"])
                meta_raw = (cached or {}).get("identity_metadata") if cached else None
                if meta_raw:
                    meta = _json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                else:
                    manifest = _fetch_ipfs_manifest(row["ipfs_cid"], row["agent_id"])
                    if not manifest:
                        continue
                    meta = manifest.model_dump()
                await loop.run_in_executor(
                    None, lambda m=meta, a=row["agent_id"]: embed_agent_capabilities(a, m)
                )
            except Exception as _e:
                logger.warning("Embedding backfill failed for %s: %s", row["agent_id"], _e)

    backfill_task = asyncio.create_task(_backfill_embeddings())

    # 6. Charger BAAI/bge-m3 dans le thread principal (event loop thread).
    #    run_in_executor appelle os._exit() silencieusement sur Windows quand
    #    PyTorch s'initialise dans un worker thread — chargement synchrone ici = safe.
    try:
        logger.info("Chargement BAAI/bge-m3…")
        from app.services.matching_service import _get_model
        _get_model()
        logger.info("BAAI/bge-m3 prêt ✓")
    except Exception as _e:
        logger.warning("BAAI/bge-m3 non chargé (matching dégradé): %s", _e)

    # 7. Démarrer tunnel + watchdog
    await start_ngrok()
    await start_watchdog()

    yield

    # Arrêt propre — gather absorbe le CancelledError sans le perdre
    backfill_task.cancel()
    await asyncio.gather(backfill_task, return_exceptions=True)
    await stop_watchdog()
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
async def serve_ipfs(cid: str):
    """Proxy IPFS content to judge containers via host.docker.internal → Pinata.
    Injects challenge_token if a validation round is active for this CID."""
    import httpx
    from app.services.judge_service import _CHALLENGE_STORE
    for gateway in [
        f"https://gateway.pinata.cloud/ipfs/{cid}",
        f"https://ipfs.io/ipfs/{cid}",
    ]:
        try:
            r = httpx.get(gateway, timeout=15, follow_redirects=True)
            if r.status_code == 200:
                data = r.json()
                token = _CHALLENGE_STORE.get(cid)
                if token:
                    data["challenge_token"] = token
                return JSONResponse(data)
        except Exception:
            continue
    raise HTTPException(404, detail=f"CID {cid} not found on IPFS")


@app.get("/tunnel", tags=["system"])
async def tunnel_info():
    url       = get_ngrok_url()
    endpoints = get_all_endpoints()
    return {
        "tunnel_url": url,
        "active":     url is not None,
        "endpoints":  endpoints,
    }

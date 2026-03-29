from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="AgentMarket API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "environment": settings.environment,
        "chain_id": settings.chain_id,
        "identity_registry": settings.identity_registry_address or "not_deployed",
    }
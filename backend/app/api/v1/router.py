from fastapi import APIRouter
from app.api.v1.agents import router as agents_router
from app.api.v1.reputation import router as reputation_router

router = APIRouter(prefix="/api/v1")
router.include_router(agents_router)
router.include_router(reputation_router)

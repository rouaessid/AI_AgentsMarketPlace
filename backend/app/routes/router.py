from fastapi import APIRouter
from app.routes.agents import router as agents_router
from app.routes.reputation import router as reputation_router
from app.routes.tasks import router as tasks_router
from app.routes.auth import router as auth_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(agents_router)
router.include_router(reputation_router)
router.include_router(tasks_router)

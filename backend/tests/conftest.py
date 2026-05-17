import pytest
from app.db.database import init_db


@pytest.fixture(scope="session", autouse=True)
def ensure_db():
    """Crée toutes les tables manquantes avant les tests (create_all est idempotent)."""
    init_db()

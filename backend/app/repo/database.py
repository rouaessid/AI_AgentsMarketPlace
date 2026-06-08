"""
database.py — SQLAlchemy engine + session.
Les entités (tables) sont définies dans app/entities/.
"""
from __future__ import annotations
import logging
from pathlib import Path

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Engine ─────────────────────────────────────────────────────────────────────
_db_path     = Path(settings.storage_path) / "agentmarket.db"
_sqlite_url  = f"sqlite:///{_db_path}"
DATABASE_URL = settings.database_url if settings.database_url else _sqlite_url

_is_postgres = DATABASE_URL.startswith("postgresql")

_engine = create_engine(
    DATABASE_URL,
    connect_args={} if _is_postgres else {"check_same_thread": False},
    echo=False,
)
SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    """Yield a DB session. Use as context manager: `with get_session() as s:`."""
    return SessionLocal()


# ── ORM Base ───────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    metadata = MetaData()


# ── Init ───────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    # Import entities so they register themselves with Base.metadata
    import app.entities.agent    # noqa: F401
    import app.entities.pipeline # noqa: F401
    import app.entities.access   # noqa: F401

    from sqlalchemy import text
    if not _is_postgres:
        _db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    with _engine.connect() as conn:
        if _is_postgres:
            conn.execute(text(
                "ALTER TABLE agent_embeddings ADD COLUMN IF NOT EXISTS "
                "registration_status VARCHAR NOT NULL DEFAULT 'active'"
            ))
        else:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(agent_embeddings)")).fetchall()]
            if "registration_status" not in cols:
                conn.execute(text(
                    "ALTER TABLE agent_embeddings ADD COLUMN "
                    "registration_status TEXT NOT NULL DEFAULT 'active'"
                ))
                conn.execute(text("UPDATE agent_embeddings SET registration_status = 'active'"))
        conn.commit()
    logger.info("DB initialisee: %s", DATABASE_URL.split("@")[-1])



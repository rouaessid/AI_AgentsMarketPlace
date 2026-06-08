"""
database.py — SQLAlchemy engine + table definitions.

Source-of-truth split:
  - The Graph       : events blockchain (identity, escrow, validation, reputation)
  - IPFS            : manifests agents, justifications juges, outputs pipelines
  - On-chain (RPC)  : état courant des contrats (scores, stakes, paiements)
  - PostgreSQL      : données locales impossibles elsewhere

Tables (5):
  agent_embeddings  — agent_id + vecteur ML (matching sémantique)
  agent_telemetry   — métriques runtime sandbox (latence, uptime)
  access_grants     — accès achetés (lien task_id → EscrowManager on-chain)
  validation_sessions — état transitoire workflow validation
  pipeline_tasks    — orchestration pipeline off-chain
"""
from __future__ import annotations
import logging
from pathlib import Path

from sqlalchemy import Column, Float, Integer, MetaData, String, Text, create_engine
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


# ══════════════════════════════════════════════════════════════════════════════
#  RUNTIME REGISTRY — written by agent_service (registration flow)
# ══════════════════════════════════════════════════════════════════════════════

class AgentEmbedding(Base):
    """
    Registre minimal — une ligne par agentId.
    registration_status : état transitoire (pending_signature / pending_index / active).
    capability_embedding : vecteur ML calculé après indexation The Graph.
    """
    __tablename__ = "agent_embeddings"

    agent_id              = Column(String, primary_key=True)
    registration_status   = Column(String, nullable=False, default="active")  # persisté localement, active = indexé sur The Graph
    capability_embedding  = Column(Text, nullable=True)  # BAAI/bge-m3 vector


# ══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY ZONE — written by backend runtime (proxy / health checks)
# ══════════════════════════════════════════════════════════════════════════════

class AgentTelemetry(Base):
    """
    Métriques runtime sandbox — les seules qui ne peuvent pas venir d'ailleurs.
    avg_response_time : mesuré par le proxy en ms (pas on-chain).
    uptime            : health check réseau (pas on-chain).
    Tout le reste (tasks_performed, last_active, etc.) est dérivable via ScoreRecorded (The Graph).
    """
    __tablename__ = "agent_telemetry"

    agent_id          = Column(String, primary_key=True)
    avg_response_time = Column(Float,  nullable=True)  # secondes, mesuré par sandbox


# ══════════════════════════════════════════════════════════════════════════════
#  APPLICATION LOGIC — written by backend (never mirrors blockchain events)
# ══════════════════════════════════════════════════════════════════════════════

class AccessGrant(Base):
    """
    Purchase grants — buyer paid, backend records access.
    buyer_wallet et paid_wei sont on-chain (EscrowManager) — vérifiés à la demande d'accès.
    """
    __tablename__ = "access_grants"

    id         = Column(String, primary_key=True)
    agent_id   = Column(String, nullable=False, index=True)
    task_id    = Column(String, nullable=False, unique=True)
    status     = Column(String, nullable=False, default="granted")
    granted_at = Column(String, nullable=False)


class ValidationSession(Base):
    """
    Suivi workflow de validation — état transitoire uniquement.
    consensus_verdict, aggregated_score, finished_at → getTask(val_task_id) on-chain.
    """
    __tablename__ = "validation_sessions"

    agent_id    = Column(String, primary_key=True)
    val_task_id = Column(String, nullable=True)
    started_at  = Column(String, nullable=True)



class PipelineTask(Base):
    """
    Orchestration pipeline — état local uniquement.
    buyer_wallet et tx_hash → on-chain (EscrowManager).
    final_output → IPFS (immuable), seul le CID est stocké ici.
    """
    __tablename__ = "pipeline_tasks"

    id                      = Column(String, primary_key=True)
    task_prompt             = Column(Text,   nullable=False)
    mode                    = Column(String, nullable=False)
    plan_json               = Column(Text,   nullable=True)
    selected_agents_json    = Column(Text,   nullable=True)
    steps_json              = Column(Text,   nullable=True)
    status                  = Column(String, nullable=False, default="planning")
    final_output_ipfs_cid   = Column(String, nullable=True)
    val_task_id             = Column(String, nullable=True)
    pack_id                 = Column(String, nullable=True)
    pack_name               = Column(String, nullable=True)
    access_granted_at       = Column(String, nullable=True)
    access_expires_at       = Column(String, nullable=True)
    created_at              = Column(String, nullable=False)
    finished_at             = Column(String, nullable=True)


# ── Init ───────────────────────────────────────────────────────────────────────



def init_db() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
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



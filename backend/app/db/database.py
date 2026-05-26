"""
database.py — SQLAlchemy engine + table definitions.

Source-of-truth split:
  - The Graph  : all blockchain events (escrow, staking, validation, reputation, agent identity)
  - IPFS       : agent manifest (docker_image, capabilities, pricing, readme)
  - PostgreSQL  : backend-only data that cannot come from chain or IPFS

Tables kept (6):
  agents            — slim runtime registry (agent_id, embedding, docker_image, owner, status)
  agent_telemetry   — runtime metrics: latency, usage, uptime
  access_grants     — purchase/access logic
  validation_sessions — judge workflow status/timing
  judge_verdicts    — individual judge justifications (off-chain text)
  pipeline_tasks    — pipeline orchestration state

Tables removed (written by blockchain_indexer, now served by The Graph):
  escrow_events, staking_events, validation_events, reputation_events,
  collaboration_log, indexer_state, agent_versions, judge_reputation
"""
from __future__ import annotations
import logging
from pathlib import Path

from sqlalchemy import Column, Float, Integer, MetaData, String, Text, create_engine, text
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
    Minimal backend registry — one row per agentId.

    Source of truth split:
      - The Graph  : tokenId, owner, status, agentType, agentURI (AgentCreated event)
      - IPFS       : full manifest (capabilities, pricing, docker_image, readme...)
      - Here       : capability_embedding (ML vector), ipfs_cid (IPFS lookup key),
                     status (pending tracking before on-chain confirmation)
    """
    __tablename__ = "agent_embeddings"

    agent_id             = Column(String, primary_key=True)
    capability_embedding = Column(Text,   nullable=True)   # BAAI/bge-m3 vector
    ipfs_cid             = Column(String, nullable=True)   # to fetch IPFS manifest
    status               = Column(String, nullable=False, default="pending_signature")


# ══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY ZONE — written by backend runtime (proxy / health checks)
# ══════════════════════════════════════════════════════════════════════════════

class AgentTelemetry(Base):
    """
    Ephemeral metrics that cannot go on-chain (real-time, per-ms).
    Updated by agent_service.update_run_metrics() after every execution.
    """
    __tablename__ = "agent_telemetry"

    agent_id             = Column(String, primary_key=True)
    tasks_performed      = Column(Integer, nullable=False, default=0)
    usage_count          = Column(Integer, nullable=False, default=0)
    avg_response_time    = Column(Float,   nullable=True)        # seconds
    task_completion_rate = Column(Float,   nullable=True)        # 0-100
    uptime               = Column(Float,   nullable=True)        # 0-100 %
    last_active          = Column(String,  nullable=True)        # ISO-8601

    monthly_tasks_json   = Column(Text,    nullable=True)        # [int x 12]
    weekly_success_json  = Column(Text,    nullable=True)        # [float x 7]

    reputation_score     = Column(Float,   nullable=True, default=0.0)
    success_rate         = Column(Float,   nullable=True, default=0.0)
    val_count            = Column(Integer, nullable=False, default=0)


# ══════════════════════════════════════════════════════════════════════════════
#  APPLICATION LOGIC — written by backend (never mirrors blockchain events)
# ══════════════════════════════════════════════════════════════════════════════

class AccessGrant(Base):
    """Purchase grants — buyer paid, backend records access."""
    __tablename__ = "access_grants"

    id           = Column(String,  primary_key=True)
    agent_id     = Column(String,  nullable=False, index=True)
    buyer_wallet = Column(String,  nullable=False)
    task_id      = Column(String,  nullable=False, unique=True)
    paid_wei     = Column(String,  nullable=False, default="0")
    tx_hash      = Column(String,  nullable=True)
    status       = Column(String,  nullable=False, default="pending")
    granted_at   = Column(String,  nullable=False)


class ValidationSession(Base):
    __tablename__ = "validation_sessions"

    agent_id          = Column(String, primary_key=True)
    val_task_id       = Column(String, nullable=True)
    status            = Column(String, nullable=False, default="pending")
    consensus_verdict = Column(String, nullable=True)
    aggregated_score  = Column(Integer, nullable=True)
    started_at        = Column(String, nullable=True)
    finished_at       = Column(String, nullable=True)


class JudgeVerdict(Base):
    __tablename__ = "judge_verdicts"

    id            = Column(String,  primary_key=True)
    agent_id      = Column(String,  nullable=False, index=True)
    judge_id      = Column(String,  nullable=False)
    judge_name    = Column(String,  nullable=False)
    score         = Column(Integer, nullable=False)
    justification = Column(Text,    nullable=False)
    verdict       = Column(String,  nullable=False)
    created_at    = Column(String,  nullable=False)


class PipelineTask(Base):
    """Off-chain pipeline orchestration — never a mirror of on-chain events."""
    __tablename__ = "pipeline_tasks"

    id                   = Column(String,  primary_key=True)
    task_prompt          = Column(Text,    nullable=False)
    mode                 = Column(String,  nullable=False)           # "solo" | "pipeline"
    plan_json            = Column(Text,    nullable=True)
    selected_agents_json = Column(Text,    nullable=True)
    steps_json           = Column(Text,    nullable=True)
    status               = Column(String,  nullable=False, default="planning")
    final_output         = Column(Text,    nullable=True)
    val_task_id          = Column(String,  nullable=True)
    buyer_wallet         = Column(String,  nullable=True)
    created_at           = Column(String,  nullable=False)
    finished_at          = Column(String,  nullable=True)
    pack_id              = Column(String,  nullable=True)
    pack_name            = Column(String,  nullable=True)
    access_granted_at    = Column(String,  nullable=True)
    access_expires_at    = Column(String,  nullable=True)
    tx_hash              = Column(String,  nullable=True)


# ── Init ───────────────────────────────────────────────────────────────────────

def _get_columns(conn, table: str) -> set[str]:
    """Return existing column names for a table — works for SQLite and Postgres."""
    if _is_postgres:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
        ), {"t": table})
    else:
        rows = conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[0] if _is_postgres else row[1] for row in rows}


def _apply_migrations() -> None:
    """Add columns that create_all cannot handle (existing tables)."""
    with _engine.connect() as conn:
        # pipeline_tasks migrations
        pt_cols = _get_columns(conn, "pipeline_tasks")
        for col, typedef in [
            ("pack_id",           "TEXT"),
            ("pack_name",         "TEXT"),
            ("access_granted_at", "TEXT"),
            ("access_expires_at", "TEXT"),
            ("tx_hash",           "TEXT"),
        ]:
            if col not in pt_cols:
                conn.execute(text(f"ALTER TABLE pipeline_tasks ADD COLUMN {col} {typedef}"))
                conn.commit()
                logger.info("Migration: added pipeline_tasks.%s", col)


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    if not _is_postgres:
        _db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    _apply_migrations()
    logger.info("DB initialisee: %s", DATABASE_URL.split("@")[-1])



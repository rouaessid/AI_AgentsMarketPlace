"""
database.py — SQLAlchemy engine + table definitions.

Two zones are strictly separated:
  - Identity tables  : populated ONLY by blockchain_indexer.py (events)
  - Telemetry tables : populated ONLY by backend runtime (latency, uptime)

Using SQLite now.  To switch to PostgreSQL later, change DATABASE_URL only:
  DATABASE_URL = "postgresql://user:pass@host/dbname"
No other code changes required.
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
_db_path    = Path(settings.storage_path) / "agentmarket.db"
DATABASE_URL = f"sqlite:///{_db_path}"

# connect_args only needed for SQLite (allows multi-thread access)
_engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
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
#  IDENTITY ZONE — written by blockchain_indexer.py ONLY
# ══════════════════════════════════════════════════════════════════════════════

class Agent(Base):
    """
    Canonical identity record.  One row per agentId.
    Source of truth: IdentityRegistry AgentCreated event.
    """
    __tablename__ = "agents"

    agent_id         = Column(String,  primary_key=True)
    registration_id  = Column(String,  nullable=False)          # internal UUID
    current_token_id = Column(Integer, nullable=True)           # latest NFT tokenId
    owner_address    = Column(String,  nullable=False, default="")
    docker_image     = Column(String,  nullable=True)
    status           = Column(String,  nullable=False, default="active")
    tx_hash          = Column(String,  nullable=True)           # registration tx
    block_number     = Column(Integer, nullable=True)           # block of AgentCreated
    registered_at    = Column(String,  nullable=True)           # ISO-8601

    # IPFS / ERC-8004
    agent_uri        = Column(String,  nullable=True)           # ipfs://Qm...
    ipfs_cid         = Column(String,  nullable=True)

    # Snapshot of immutable fields from IPFS manifest (for fast queries)
    name             = Column(String,  nullable=True)
    version          = Column(String,  nullable=True)
    price_per_task   = Column(Float,   nullable=True, default=0.0)
    stake_amount     = Column(Float,   nullable=True, default=0.0)
    agent_type       = Column(Integer, nullable=True, default=0)    # 0=Provider, 1=Judge

    # Raw JSON of the full AgentRegistrationFile (identity only, no metrics)
    identity_metadata = Column(Text,   nullable=True)


class AgentVersion(Base):
    """
    One row per NFT token (= per version).
    Source of truth: IdentityRegistry AgentVersionMinted event.
    """
    __tablename__ = "agent_versions"

    token_id     = Column(Integer, primary_key=True)   # NFT tokenId — unique per version
    agent_id     = Column(String,  nullable=False, index=True)
    version      = Column(String,  nullable=False)
    agent_uri    = Column(String,  nullable=True)       # IPFS URI for this version
    docker_image = Column(String,  nullable=True)
    block_number = Column(Integer, nullable=True)
    minted_at    = Column(String,  nullable=True)       # ISO-8601


# ══════════════════════════════════════════════════════════════════════════════
#  TELEMETRY ZONE — written by backend runtime ONLY (proxy / health checks)
# ══════════════════════════════════════════════════════════════════════════════

class AgentTelemetry(Base):
    """
    Ephemeral metrics that cannot go on-chain (real-time, per-ms).
    Updated by agent_service.update_run_metrics() after every execution.

    Everything reputation-related (reputation_score, success_rate) will
    move to reputation_events once ReputationContract is deployed.
    """
    __tablename__ = "agent_telemetry"

    agent_id             = Column(String, primary_key=True)
    tasks_performed      = Column(Integer, nullable=False, default=0)
    usage_count          = Column(Integer, nullable=False, default=0)
    avg_response_time    = Column(Float,   nullable=True)        # seconds
    task_completion_rate = Column(Float,   nullable=True)        # 0-100
    uptime               = Column(Float,   nullable=True)        # 0-100 %
    last_active          = Column(String,  nullable=True)        # ISO-8601

    # Serialized arrays for charts — JSON strings
    monthly_tasks_json   = Column(Text,    nullable=True)        # [int x 12]
    weekly_success_json  = Column(Text,    nullable=True)        # [float x 7]

    # Temporary reputation placeholders until ReputationContract is live
    reputation_score     = Column(Float,   nullable=True, default=0.0)
    success_rate         = Column(Float,   nullable=True, default=0.0)
    val_count            = Column(Integer, nullable=False, default=0)   # internal


# ══════════════════════════════════════════════════════════════════════════════
#  BLOCKCHAIN EVENT ZONE — written by blockchain_indexer.py ONLY
# ══════════════════════════════════════════════════════════════════════════════

class EscrowEvent(Base):
    """
    One row per EscrowManager event (PaymentDeposited / FundsReleased / ClientRefunded).
    """
    __tablename__ = "escrow_events"

    id         = Column(String,  primary_key=True)   # f"{tx_hash}-{log_index}"
    task_id    = Column(String,  nullable=False, index=True)
    event_type = Column(String,  nullable=False)      # "deposited"|"released"|"refunded"
    agent_id   = Column(String,  nullable=True,  index=True)
    client     = Column(String,  nullable=True)
    provider   = Column(String,  nullable=True)
    amount_wei = Column(String,  nullable=True)       # string to avoid int overflow
    tx_hash    = Column(String,  nullable=True)
    block_number = Column(Integer, nullable=True)
    created_at = Column(String,  nullable=True)       # ISO-8601


class StakingEvent(Base):
    """
    One row per StakingContract event (Staked / Unstaked / Slashed).
    """
    __tablename__ = "staking_events"

    id           = Column(String,  primary_key=True)
    event_type   = Column(String,  nullable=False)    # "staked"|"unstaked"|"slashed"
    agent_wallet = Column(String,  nullable=False, index=True)
    amount_wei   = Column(String,  nullable=True)
    reason       = Column(String,  nullable=True)     # only for Slashed
    tx_hash      = Column(String,  nullable=True)
    block_number = Column(Integer, nullable=True)
    created_at   = Column(String,  nullable=True)


class ValidationEvent(Base):
    """
    One row per ValidationRegistry event.
    """
    __tablename__ = "validation_events"

    id           = Column(String,  primary_key=True)
    task_id      = Column(String,  nullable=False, index=True)
    agent_id     = Column(String,  nullable=True,  index=True)
    event_type   = Column(String,  nullable=False)
    # "request"|"judges_assigned"|"vote_committed"|"vote_revealed"|"verdict"|"expired"
    verdict      = Column(String,  nullable=True)     # "VALID"|"INVALID"|None
    score        = Column(Float,   nullable=True)
    judge_id     = Column(String,  nullable=True)
    tx_hash      = Column(String,  nullable=True)
    block_number = Column(Integer, nullable=True)
    created_at   = Column(String,  nullable=True)


class ReputationEvent(Base):
    """
    One row per ReputationRegistry NewFeedback / FeedbackRevoked event.
    Populated by blockchain_indexer.py only.

    agent_token_id : ERC-721 tokenId (= agentId in ERC-8004 spec)
    agent_id       : string agentId (denormalised from IdentityRegistry for easy queries)
    tag1 / tag2    : signal category — "successRate" | "starred" | "eigenTrust" | ...
    value          : int128 raw feedback value (sign encodes direction)
    value_decimals : decimal precision of value
    """
    __tablename__ = "reputation_events"

    id               = Column(String,  primary_key=True)   # tx_hash-log_index
    event_type       = Column(String,  nullable=False)     # "new_feedback" | "revoked"
    agent_token_id   = Column(Integer, nullable=False, index=True)
    agent_id         = Column(String,  nullable=True,  index=True)
    client_address   = Column(String,  nullable=False)
    feedback_index   = Column(Integer, nullable=False)
    value            = Column(Integer, nullable=False, default=0)
    value_decimals   = Column(Integer, nullable=False, default=0)
    tag1             = Column(String,  nullable=False, default="")
    tag2             = Column(String,  nullable=True,  default="")
    endpoint         = Column(String,  nullable=True)
    feedback_uri     = Column(String,  nullable=True)
    feedback_hash    = Column(String,  nullable=True)
    is_revoked       = Column(Integer, nullable=False, default=0)   # 0/1
    tx_hash          = Column(String,  nullable=True)
    block_number     = Column(Integer, nullable=True)
    created_at       = Column(String,  nullable=True)


# ══════════════════════════════════════════════════════════════════════════════
#  INDEXER STATE — written by blockchain_indexer.py to survive restarts
# ══════════════════════════════════════════════════════════════════════════════

class IndexerState(Base):
    """
    Stores the last processed block per contract so the indexer
    can resume from where it left off after a backend restart.
    """
    __tablename__ = "indexer_state"

    contract_name = Column(String,  primary_key=True)  # e.g. "identity_registry"
    last_block    = Column(Integer, nullable=False, default=0)
    updated_at    = Column(String,  nullable=True)


# ══════════════════════════════════════════════════════════════════════════════
#  LEGACY TABLES (kept for backward-compat during transition)
# ══════════════════════════════════════════════════════════════════════════════

class AccessGrant(Base):
    """Access grants — will be replaced by EscrowEvent once indexer is live."""
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


# ── Init ───────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    logger.info("DB initialisee (SQLAlchemy): %s", _db_path)


# ── Legacy helper (used by access_repo.py + agent_repo.py until fully migrated)

def get_connection():
    """
    Raw sqlite3 connection for legacy repos still using raw SQL.
    Will be removed once all repos are migrated to SQLAlchemy sessions.
    """
    import sqlite3
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

from __future__ import annotations

from sqlalchemy import Column, String

from app.repo.database import Base


class AccessGrant(Base):
    """
    Purchase grants — buyer paid, backend records access.
    buyer_wallet et paid_wei sont on-chain (EscrowManager).
    """
    __tablename__ = "access_grants"

    id         = Column(String, primary_key=True)
    agent_id   = Column(String, nullable=False, index=True)
    task_id    = Column(String, nullable=False, unique=True)
    status     = Column(String, nullable=False, default="granted")
    granted_at = Column(String, nullable=False)


class ValidationSession(Base):
    """Suivi workflow de validation — état transitoire uniquement."""
    __tablename__ = "validation_sessions"

    agent_id    = Column(String, primary_key=True)
    val_task_id = Column(String, nullable=True)
    started_at  = Column(String, nullable=True)

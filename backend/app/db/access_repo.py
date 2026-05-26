from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func

from app.db.database import AccessGrant, JudgeVerdict, ValidationSession, get_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Access Grants ─────────────────────────────────────────────────────────────

def create_access_grant(
    agent_id:     str,
    buyer_wallet: str,
    task_id:      str,
    paid_wei:     str = "0",
    tx_hash:      str | None = None,
) -> str:
    grant_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(AccessGrant(
            id=grant_id, agent_id=agent_id,
            buyer_wallet=buyer_wallet.lower(), task_id=task_id,
            paid_wei=paid_wei, tx_hash=tx_hash,
            status="granted", granted_at=_now(),
        ))
        s.commit()
    return grant_id


def has_any_access_grant(buyer_wallet: str) -> bool:
    with get_session() as s:
        return s.query(AccessGrant).filter(
            func.lower(AccessGrant.buyer_wallet) == buyer_wallet.lower()
        ).first() is not None


def get_access_grant(agent_id: str, buyer_wallet: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = (
            s.query(AccessGrant)
            .filter(
                AccessGrant.agent_id == agent_id,
                func.lower(AccessGrant.buyer_wallet) == buyer_wallet.lower(),
            )
            .order_by(AccessGrant.granted_at.desc())
            .first()
        )
        if not row:
            return None
        return {c.name: getattr(row, c.name) for c in AccessGrant.__table__.columns}


def get_access_grant_by_task(task_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.query(AccessGrant).filter(AccessGrant.task_id == task_id).first()
        if not row:
            return None
        return {c.name: getattr(row, c.name) for c in AccessGrant.__table__.columns}


# ── Validation Sessions ───────────────────────────────────────────────────────

def upsert_validation_session(
    agent_id:          str,
    val_task_id:       str | None = None,
    status:            str = "pending",
    consensus_verdict: str | None = None,
    aggregated_score:  int | None = None,
    started_at:        str | None = None,
    finished_at:       str | None = None,
) -> None:
    with get_session() as s:
        row = s.get(ValidationSession, agent_id)
        if row:
            row.val_task_id       = val_task_id
            row.status            = status
            row.consensus_verdict = consensus_verdict
            row.aggregated_score  = aggregated_score
            if started_at is not None:
                row.started_at = started_at
            row.finished_at = finished_at
        else:
            s.add(ValidationSession(
                agent_id=agent_id, val_task_id=val_task_id, status=status,
                consensus_verdict=consensus_verdict, aggregated_score=aggregated_score,
                started_at=started_at, finished_at=finished_at,
            ))
        s.commit()


def get_validation_session(agent_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.get(ValidationSession, agent_id)
        if not row:
            return None
        return {c.name: getattr(row, c.name) for c in ValidationSession.__table__.columns}


# ── Judge Verdicts ────────────────────────────────────────────────────────────

def insert_judge_verdict(
    agent_id:      str,
    judge_id:      str,
    judge_name:    str,
    score:         int,
    justification: str,
    verdict:       str,
) -> None:
    with get_session() as s:
        s.add(JudgeVerdict(
            id=str(uuid.uuid4()), agent_id=agent_id, judge_id=judge_id,
            judge_name=judge_name, score=score, justification=justification,
            verdict=verdict, created_at=_now(),
        ))
        s.commit()


def get_judge_verdicts(agent_id: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = (
            s.query(JudgeVerdict)
            .filter(JudgeVerdict.agent_id == agent_id)
            .order_by(JudgeVerdict.created_at)
            .all()
        )
        return [{c.name: getattr(r, c.name) for c in JudgeVerdict.__table__.columns} for r in rows]


def get_verdicts_by_judge(judge_id: str) -> list[dict[str, Any]]:
    with get_session() as s:
        rows = (
            s.query(JudgeVerdict)
            .filter(JudgeVerdict.judge_id == judge_id)
            .order_by(JudgeVerdict.created_at.desc())
            .all()
        )
        return [{c.name: getattr(r, c.name) for c in JudgeVerdict.__table__.columns} for r in rows]


def clear_judge_verdicts(agent_id: str) -> None:
    with get_session() as s:
        s.query(JudgeVerdict).filter(JudgeVerdict.agent_id == agent_id).delete()
        s.commit()


def reset_stale_validations() -> int:
    with get_session() as s:
        count = (
            s.query(ValidationSession)
            .filter(ValidationSession.status.in_(["pending", "in_progress"]))
            .update(
                {"status": "awaiting_run", "val_task_id": None,
                 "started_at": None, "finished_at": None},
                synchronize_session=False,
            )
        )
        s.commit()
        return count

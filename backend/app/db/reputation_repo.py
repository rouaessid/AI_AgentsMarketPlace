"""
reputation_repo.py — DB helpers for reputation_events table.

Written ONLY by blockchain_indexer.py (NewFeedback / FeedbackRevoked events).
Read by reputation endpoint and future EigenTrust engine.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import ReputationEvent, get_session

logger = logging.getLogger(__name__)


def insert_reputation_event(
    event_id:      str,
    event_type:    str,          # "new_feedback" | "revoked"
    agent_token_id: int,
    client_address: str,
    feedback_index: int,
    value:         int   = 0,
    value_decimals: int  = 0,
    tag1:          str   = "",
    tag2:          str   = "",
    endpoint:      str   = "",
    feedback_uri:  str   = "",
    feedback_hash: str   = "",
    is_revoked:    int   = 0,
    tx_hash:       str   = "",
    block_number:  int   = 0,
    agent_id:      str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as s:
        if s.get(ReputationEvent, event_id):
            return
        s.add(ReputationEvent(
            id=event_id,
            event_type=event_type,
            agent_token_id=agent_token_id,
            agent_id=agent_id,
            client_address=client_address,
            feedback_index=feedback_index,
            value=value,
            value_decimals=value_decimals,
            tag1=tag1,
            tag2=tag2,
            endpoint=endpoint,
            feedback_uri=feedback_uri,
            feedback_hash=feedback_hash,
            is_revoked=is_revoked,
            tx_hash=tx_hash,
            block_number=block_number,
            created_at=now,
        ))
        s.commit()


def mark_revoked(agent_token_id: int, client_address: str, feedback_index: int) -> None:
    with get_session() as s:
        rows = (
            s.query(ReputationEvent)
            .filter_by(
                agent_token_id=agent_token_id,
                client_address=client_address,
                feedback_index=feedback_index,
            )
            .all()
        )
        for row in rows:
            row.is_revoked = 1
        s.commit()


def get_reputation_signals(agent_token_id: int) -> list[dict[str, Any]]:
    """Return all non-revoked feedback signals for a given tokenId."""
    with get_session() as s:
        rows = (
            s.query(ReputationEvent)
            .filter_by(agent_token_id=agent_token_id, is_revoked=0)
            .filter(ReputationEvent.event_type == "new_feedback")
            .order_by(ReputationEvent.block_number)
            .all()
        )
        return [
            {
                "feedback_index":  r.feedback_index,
                "client_address":  r.client_address,
                "value":           r.value,
                "value_decimals":  r.value_decimals,
                "tag1":            r.tag1,
                "tag2":            r.tag2,
                "tx_hash":         r.tx_hash,
                "block_number":    r.block_number,
                "created_at":      r.created_at,
            }
            for r in rows
        ]


def get_latest_eigentrust_score(agent_token_id: int) -> float | None:
    """
    Return the most recent EigenTrust final_score (0-100) written on-chain
    for this agent, or None if no eigenTrust feedback exists yet.
    """
    with get_session() as s:
        row = (
            s.query(ReputationEvent)
            .filter_by(agent_token_id=agent_token_id, is_revoked=0)
            .filter(ReputationEvent.tag1 == "eigenTrust")
            .order_by(ReputationEvent.block_number.desc())
            .first()
        )
        if row is None:
            return None
        dec = row.value_decimals or 0
        raw = row.value / (10 ** dec) if dec else float(row.value)
        return round(raw * 100, 1)


def get_aggregated_score(agent_token_id: int) -> dict[str, Any]:
    """
    Compute a simple aggregated score per tag1 from raw on-chain signals.
    Returns: { tag1 -> { count, sum, average } }
    """
    signals = get_reputation_signals(agent_token_id)
    per_tag: dict[str, dict] = {}
    for s in signals:
        tag = s["tag1"] or "unknown"
        if tag not in per_tag:
            per_tag[tag] = {"count": 0, "sum": 0}
        per_tag[tag]["count"] += 1
        # Normalise value by decimals for aggregation
        decimals = s["value_decimals"] or 0
        normalised = s["value"] / (10 ** decimals) if decimals else s["value"]
        per_tag[tag]["sum"] += normalised

    result = {}
    for tag, data in per_tag.items():
        result[tag] = {
            "count":   data["count"],
            "sum":     data["sum"],
            "average": round(data["sum"] / data["count"], 4) if data["count"] else 0,
        }
    return result

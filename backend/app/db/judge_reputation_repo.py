"""
judge_reputation_repo.py — Opérations DB pour la réputation des juges.

agreement_rate = agreement_count / total_validations
  → 0.5 par défaut (neutre) avant la 1ère validation
  → mis à jour après chaque session de validation
  → mirrored on-chain via ReputationRegistry (tag1="judgeAccuracy")
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db.database import JudgeReputation, get_session


def get_judge_reputation(judge_id: str) -> dict:
    """Retourne la réputation d'un juge. Crée la ligne si absente (rate=0.5)."""
    with get_session() as s:
        row = s.get(JudgeReputation, judge_id)
        if not row:
            row = JudgeReputation(
                judge_id=judge_id,
                total_validations=0,
                agreement_count=0,
                agreement_rate=0.5,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
        return {
            "judge_id":          row.judge_id,
            "total_validations": row.total_validations,
            "agreement_count":   row.agreement_count,
            "agreement_rate":    row.agreement_rate,
        }


def update_judge_agreement(judge_id: str, agreed: bool) -> float:
    """
    Incrémente total_validations (et agreement_count si agreed).
    Retourne le nouveau agreement_rate.
    """
    with get_session() as s:
        row = s.get(JudgeReputation, judge_id)
        if not row:
            row = JudgeReputation(
                judge_id=judge_id,
                total_validations=0,
                agreement_count=0,
                agreement_rate=0.5,
            )
            s.add(row)

        row.total_validations += 1
        if agreed:
            row.agreement_count += 1
        row.agreement_rate = row.agreement_count / row.total_validations
        row.updated_at = datetime.now(timezone.utc).isoformat()
        s.commit()
        return row.agreement_rate


def get_all_reputations() -> list[dict]:
    """Retourne la réputation de tous les juges connus."""
    with get_session() as s:
        rows = s.query(JudgeReputation).all()
        return [
            {
                "judge_id":          r.judge_id,
                "total_validations": r.total_validations,
                "agreement_count":   r.agreement_count,
                "agreement_rate":    r.agreement_rate,
            }
            for r in rows
        ]

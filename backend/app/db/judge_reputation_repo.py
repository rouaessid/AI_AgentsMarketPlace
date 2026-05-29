"""
judge_reputation_repo.py — Réputation des juges calculée depuis reputation_events.

Source de vérité : blockchain (ReputationRegistry)
  tag1 = "CONSENSUS" → juge a voté avec le consensus  (+1 accord)
  tag1 = "DEVIATED"  → juge a voté contre le consensus
  tag1 = "ABSENT"    → juge n'a pas voté

agreement_rate = agreement_count / total_validations
  → 0.5 par défaut (neutre) si aucune validation trouvée
"""
from __future__ import annotations

from app.db.database import ReputationEvent, get_session


def _compute_from_events(judge_id: str) -> dict:
    """
    Lit la dernière entrée judgeAccuracy depuis reputation_events.
    Le backend écrit : tag1="judgeAccuracy", tag2=judge_id, value=agreement_rate×100
    """
    with get_session() as s:
        # Prendre l'entrée la plus récente pour ce juge
        row = (
            s.query(ReputationEvent)
            .filter(
                ReputationEvent.tag1 == "judgeAccuracy",
                ReputationEvent.tag2 == judge_id,
                ReputationEvent.is_revoked == 0,
            )
            .order_by(ReputationEvent.block_number.desc())
            .first()
        )

        from app.db.database import get_connection
        conn = get_connection()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM judge_verdicts WHERE judge_id = ?", (judge_id,)
            ).fetchone()[0]
        finally:
            conn.close()

        if not row:
            return {
                "judge_id":          judge_id,
                "total_validations": total,
                "agreement_count":   0,
                "agreement_rate":    0.5,
            }

        agreement_rate = row.value / 100.0

        return {
            "judge_id":          judge_id,
            "total_validations": total,
            "agreement_count":   0,
            "agreement_rate":    agreement_rate,
        }


def get_judge_reputation(judge_id: str) -> dict:
    """Retourne la réputation d'un juge calculée depuis la blockchain."""
    return _compute_from_events(judge_id)


def update_judge_agreement(judge_id: str, agreed: bool) -> float:
    """
    Appelé par judge_service après chaque validation locale.
    Le vrai calcul vient de reputation_events (blockchain) —
    cette fonction retourne le taux recalculé immédiatement.
    Le backend écrit le résultat on-chain séparément via eigentrust_sync.
    """
    rep = _compute_from_events(judge_id)
    return rep["agreement_rate"]


def get_all_reputations() -> list[dict]:
    """Retourne la réputation de tous les juges connus depuis reputation_events."""
    with get_session() as s:
        rows = (
            s.query(ReputationEvent.tag2)
            .filter(
                ReputationEvent.tag1 == "judgeAccuracy",
                ReputationEvent.is_revoked == 0,
                ReputationEvent.tag2.isnot(None),
            )
            .distinct()
            .all()
        )
    judge_ids = [r[0] for r in rows if r[0]]
    return [_compute_from_events(jid) for jid in judge_ids]

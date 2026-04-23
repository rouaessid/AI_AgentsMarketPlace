"""
reputation.py — /api/v1/reputation endpoints.

Phase 1 : signaux bruts agrégés depuis reputation_events (on-chain).
Phase 2 : scores EigenTrust OpenRank calculés off-chain.

Architecture OpenRank :
  p  = SuccessRate normalisé  (Judge → Agent, ancre technique)
  C  = collaborations         (Agent → Agent, propagation — Phase 3)
  t  = Global-Trust           (Power Method)
  Score_Final = t × starred   (User → Agent, pondérateur contextuel)
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.identity_repo import get_agent_identity, get_all_agent_identities
from app.db.reputation_repo import get_aggregated_score, get_reputation_signals

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reputation", tags=["reputation"])


@router.get("/{agent_id}")
async def get_reputation(agent_id: str):
    """
    Retourne pour un agent :
      - signaux bruts on-chain (successRate, starred, eigenTrust...)
      - score EigenTrust OpenRank calculé à la volée

    Réponse :
    {
      "agent_id": "...",
      "token_id": 42,
      "raw_signals": {
        "successRate": { "count": 3, "sum": 280, "average": 93.3 },
        "starred":     { "count": 1, "sum": 80,  "average": 80.0 }
      },
      "eigentrust": {
        "pre_trust":     0.12,    ← part du SuccessRate normalisé
        "global_trust":  0.15,    ← score EigenTrust pur (t_i)
        "user_feedback": 0.80,    ← starred normalisé (0-1)
        "final_score":   0.14,    ← global_trust × user_feedback (normalisé)
        "converged": true,
        "iterations": 8
      },
      "signals": [ ... ]
    }
    """
    identity = get_agent_identity(agent_id)
    if not identity:
        raise HTTPException(404, detail=f"Agent {agent_id!r} introuvable")

    token_id = identity.get("current_token_id")
    if not token_id:
        return JSONResponse({
            "agent_id":   agent_id,
            "token_id":   None,
            "raw_signals": {},
            "eigentrust": None,
            "signals":    [],
            "message":    "Agent non encore enregistré on-chain",
        })

    raw_signals = get_aggregated_score(token_id)
    signals     = get_reputation_signals(token_id)

    # ── EigenTrust OpenRank (calcul sur tous les agents actifs) ────────────────
    eigentrust_data = None
    try:
        from app.services.eigentrust_service import compute_eigentrust

        all_identities = get_all_agent_identities()
        agents = [
            {"agent_id": row["agent_id"], "token_id": row["current_token_id"]}
            for row in all_identities
            if row.get("current_token_id")
        ]

        if agents:
            result = compute_eigentrust(agents)
            agent_score = result.scores_by_agent.get(agent_id)
            if agent_score:
                eigentrust_data = {
                    **agent_score,
                    "converged":  result.converged,
                    "iterations": result.iterations,
                    "agents_in_network": len(agents),
                }
    except Exception as e:
        logger.warning("EigenTrust computation failed (non-blocking): %s", e)

    return JSONResponse({
        "agent_id":    agent_id,
        "token_id":    token_id,
        "raw_signals": raw_signals,
        "eigentrust":  eigentrust_data,
        "signals":     signals,
    })


@router.get("/network/scores")
async def get_network_scores():
    """
    Calcule et retourne les scores EigenTrust pour tous les agents du réseau.
    Utile pour le dashboard et le matching de juges (Phase 4).
    """
    try:
        from app.services.eigentrust_service import compute_eigentrust

        all_identities = get_all_agent_identities()
        agents = [
            {"agent_id": row["agent_id"], "token_id": row["current_token_id"]}
            for row in all_identities
            if row.get("current_token_id")
        ]

        if not agents:
            return JSONResponse({"agents": {}, "message": "Aucun agent enregistré on-chain"})

        result = compute_eigentrust(agents)
        return JSONResponse({
            "agents":     result.scores_by_agent,
            "converged":  result.converged,
            "iterations": result.iterations,
            "network_size": len(agents),
        })

    except Exception as e:
        logger.error("Network EigenTrust failed: %s", e)
        raise HTTPException(500, detail=f"Calcul EigenTrust échoué : {e}")

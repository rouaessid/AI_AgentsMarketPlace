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
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.identity_repo import get_agent_identity, get_all_agent_identities
from app.services.graph_client import (
    get_aggregated_reputation as get_aggregated_score,
    get_reputation_events as get_reputation_signals,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reputation", tags=["reputation"])

_bg_tasks: set = set()
_NOT_ON_CHAIN = "Agent non encore enregistré on-chain"

def _fire(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


# ── Request bodies ────────────────────────────────────────────────────────────

class FeedbackBody(BaseModel):
    score:   int        # 1-5 stars
    comment: str = ""

class SimulateValidationBody(BaseModel):
    agent_id: str
    score:    int = 80  # validation score 0-100


# ── Debug: simulate a judge validation ───────────────────────────────────────
# Defined BEFORE /{agent_id} to avoid path-param conflict

@router.post("/debug/simulate-validation")
async def simulate_validation(body: SimulateValidationBody):
    """
    Debug endpoint — writes a successRate feedback on-chain using the feedback wallet.
    Simulates what ValidationRegistry.recordReputation() would do after a real judge run.
    """
    identity = get_agent_identity(body.agent_id)
    if not identity:
        raise HTTPException(404, detail=f"Agent {body.agent_id!r} introuvable")

    token_id = identity.get("current_token_id")
    if not token_id:
        raise HTTPException(400, detail=_NOT_ON_CHAIN)

    from app.services.blockchain_service import BlockchainService
    svc = BlockchainService()
    tx_hash = svc.give_feedback(token_id, body.score, 0, "successRate", "VALID_SIM")

    if not tx_hash:
        raise HTTPException(503, detail="Blockchain non disponible ou giveFeedback échoué")

    from app.services.eigentrust_sync import sync_eigentrust_onchain
    _fire(sync_eigentrust_onchain())

    return {"status": "ok", "tx_hash": tx_hash, "simulated_score": body.score, "token_id": token_id}


# ── POST /{agent_id}/feedback — user star rating ──────────────────────────────

@router.post("/{agent_id}/feedback")
async def submit_feedback(agent_id: str, body: FeedbackBody):
    """
    User submits a star rating (1-5) for an agent.
    Writes NewFeedback(tag1="starred", value=score×20) on-chain, then triggers EigenTrust sync.
    """
    if not 1 <= body.score <= 5:
        raise HTTPException(400, detail="score doit être entre 1 et 5")

    identity = get_agent_identity(agent_id)
    if not identity:
        raise HTTPException(404, detail=f"Agent {agent_id!r} introuvable")

    token_id = identity.get("current_token_id")
    if not token_id:
        raise HTTPException(400, detail=_NOT_ON_CHAIN)

    from app.services.blockchain_service import BlockchainService
    svc = BlockchainService()
    value   = body.score * 20  # 1-5 → 20-100
    comment = body.comment[:64] if body.comment else ""
    tx_hash = svc.give_feedback(token_id, value, 0, "starred", comment)

    if not tx_hash:
        raise HTTPException(503, detail="Blockchain non disponible ou feedback échoué")

    from app.services.eigentrust_sync import sync_eigentrust_onchain
    _fire(sync_eigentrust_onchain())

    return {"status": "ok", "tx_hash": tx_hash, "stars": body.score, "value": value}


# ── GET /{agent_id} ───────────────────────────────────────────────────────────

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
            "message":    _NOT_ON_CHAIN,
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
            if row.get("current_token_id") and row.get("agent_type", 0) != 1
        ]

        if agents:
            from app.services.graph_client import get_solo_scores, get_pipeline_scores
            p_overrides = {}
            for a in agents:
                scores = get_solo_scores(a["agent_id"]) or get_pipeline_scores(a["agent_id"])
                if scores:
                    nonzero = [s for s in scores if s > 0]
                    recent  = nonzero[-5:] if nonzero else []
                    if recent:
                        p_overrides[a["agent_id"]] = sum(recent) / len(recent)

            # Only compute EigenTrust if there are real signals (avoid 1/n inflation)
            has_real_signals = bool(raw_signals) or bool(p_overrides)
            if not has_real_signals:
                eigentrust_data = {
                    "pre_trust": 0.0, "global_trust": 0.0,
                    "user_feedback": 0.0, "final_score": 0.0,
                    "converged": True, "iterations": 0,
                    "agents_in_network": len(agents),
                }
            else:
                result = compute_eigentrust(agents, task_p_overrides=p_overrides or None)
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
            if row.get("current_token_id") and row.get("agent_type", 0) != 1
        ]

        if not agents:
            return JSONResponse({"agents": {}, "message": "Aucun agent enregistré on-chain"})

        from app.services.graph_client import get_solo_scores
        p_overrides = {}
        for a in agents:
            scores = get_solo_scores(a["agent_id"])
            if scores:
                nonzero = [s for s in scores if s > 0]
                recent  = nonzero[-5:] if nonzero else []
                if recent:
                    p_overrides[a["agent_id"]] = sum(recent) / len(recent)

        result = compute_eigentrust(agents, task_p_overrides=p_overrides or None)
        return JSONResponse({
            "agents":     result.scores_by_agent,
            "converged":  result.converged,
            "iterations": result.iterations,
            "network_size": len(agents),
        })

    except Exception as e:
        logger.error("Network EigenTrust failed: %s", e)
        raise HTTPException(500, detail=f"Calcul EigenTrust échoué : {e}")

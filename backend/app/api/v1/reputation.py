"""
reputation.py — /api/v1/reputation endpoints.

Sources :
  starred signals  →  The Graph (NewFeedback events, N acheteurs unbounded)
  eigenTrust score →  ReputationRegistry.eigenTrustScore[tokenId] direct RPC
"""
from __future__ import annotations
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.repo.identity_repo import get_agent_identity, get_all_agent_identities
from app.models.reputation import FeedbackBody, SimulateValidationBody
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

    from app.services.eigentrust_sync import compute_and_write_eigentrust
    _fire(compute_and_write_eigentrust(body.agent_id, 0, 0.0))

    return {"status": "ok", "tx_hash": "", "simulated_score": body.score, "token_id": token_id}


# ── POST /{agent_id}/feedback-notify — déclenche EigenTrust après tx MetaMask ──
# L'écriture on-chain (giveFeedback tag1="starred") est faite par l'utilisateur
# via MetaMask côté frontend. Ce endpoint reçoit juste le tx_hash de confirmation
# et déclenche le recalcul EigenTrust en background.

class FeedbackNotifyBody(BaseModel):
    tx_hash: str
    stars:   int = 0

@router.post("/{agent_id}/feedback-notify")
async def feedback_notify(agent_id: str, body: FeedbackNotifyBody):
    """
    Appelé par le frontend après qu'un giveFeedback(tag1='starred') a été signé
    via MetaMask et confirmé on-chain. Déclenche le recalcul EigenTrust.
    """
    identity = get_agent_identity(agent_id)
    if not identity:
        raise HTTPException(404, detail=f"Agent {agent_id!r} introuvable")

    from app.services.eigentrust_sync import compute_and_write_eigentrust
    _fire(compute_and_write_eigentrust(agent_id, 0, 0.0))

    return {"status": "ok", "tx_hash": body.tx_hash}


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

    # starred signals depuis The Graph (N acheteurs, unbounded)
    raw_signals = get_aggregated_score(token_id)
    signals     = get_reputation_signals(token_id)

    from app.services.graph_client import get_eigentrust_score, get_agent_score
    et_raw    = get_eigentrust_score(token_id)
    avg_data  = get_agent_score(agent_id)
    avg_score = float(avg_data.get("averageScore", 0)) if avg_data else 0.0

    # N=1 EigenTrust always normalises to 100 — cap at real validation average
    final_100 = min(et_raw, avg_score) if et_raw else avg_score

    # user_feedback from starred signals (0–100 scale → 0–1)
    starred    = raw_signals.get("starred", {})
    user_fb    = round(starred.get("average", 0) / 100.0, 4) if starred else None

    eigentrust_obj = {
        "final_score":   round(final_100 / 100.0, 4),
        "pre_trust":     round(avg_score  / 100.0, 4),
        "user_feedback": user_fb,
        "converged":     True,
        "iterations":    1,
        "agents_in_network": 1,
    } if (final_100 or avg_score) else None

    return JSONResponse({
        "agent_id":    agent_id,
        "token_id":    token_id,
        "raw_signals": raw_signals,
        "eigentrust":  eigentrust_obj,
        "signals":     signals,
    })


@router.get("/network/scores")
async def get_network_scores():
    """Retourne les scores EigenTrust courants pour tous les agents — direct RPC."""
    from app.services.graph_client import get_eigentrust_score

    all_identities = get_all_agent_identities()
    agents = [
        row for row in all_identities
        if row.get("current_token_id") and row.get("agent_type", 0) != 1
    ]
    if not agents:
        return JSONResponse({"agents": {}, "message": "Aucun agent enregistré on-chain"})

    scores = {}
    for row in agents:
        score = get_eigentrust_score(row["current_token_id"])
        scores[row["agent_id"]] = score
    return JSONResponse({"agents": scores, "network_size": len(agents)})

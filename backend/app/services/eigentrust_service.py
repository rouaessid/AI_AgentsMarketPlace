"""
eigentrust_service.py — OpenRank EigenTrust Engine.

FORMULES
─────────────────────────────────────────────────────────────────────────────
1. Seed Trust  p[i]
   p[i] = aggregatedScore de la tâche courante pour l'agent validé
          (lu depuis ValidationRegistry.getAgentScore() après finaliseValidation)
   task_p_overrides={agent_id: score} — obligatoire, aucun fallback historique.
   C gère déjà l'historique via ATE — additionner des moyennes historiques dans p
   doublerait l'historique.

2. Collaboration Capacity  C[j][i]  (ATE — Imbens 2021)
   uplift[j] = max( mean_pipeline[j] − mean_solo[j], 0 ) / 100
   C[j][i]   = uplift[j] / K   pour i ≠ j
   Source : ValidationRegistry.getAgentModeScores() — direct RPC, aucun délai.

3. Power Method  (Kamvar et al. 2003)
   t⁽ᵏ⁺¹⁾ = (1 − α) · Cᵀ · t⁽ᵏ⁾ + α · p̂

4. Score Final
   V[i] = t[i] × f[i]
   f[i] = starred signals depuis The Graph (N acheteurs, unbounded)

SOURCES
   p  ←  task_p_overrides (blockchain receipt — obligatoire)
   C  ←  ValidationRegistry.getAgentModeScores() (direct RPC)
   f  ←  ReputationRegistry NewFeedback(tag1="starred") (The Graph)
   t  ←  Power Method sur (p, C)
   V  ←  t × f
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging

import numpy as np
from web3 import Web3

from app.core.config import get_settings
from app.schemas.reputation import EigenTrustResult
from app.services.graph_client import get_reputation_events as _get_rep_events

logger   = logging.getLogger(__name__)
settings = get_settings()

ALPHA    = 0.15
MAX_ITER = 100
EPSILON  = 1e-6

from app.core.abis import VALIDATION_REGISTRY_ABI as _MODE_SCORES_ABI
from app.core.abis import IDENTITY_REGISTRY_ABI   as _IDENTITY_ABI


def _get_mode_scores(agent_id: str) -> tuple[float, float]:
    """
    Return (mean_solo, mean_pipeline) from ValidationRegistry direct RPC.
    Returns (0.0, 0.0) if RPC unavailable or no data.
    """
    rpc           = settings.rpc_url
    addr          = settings.validation_registry_address
    identity_addr = settings.identity_registry_address
    if not rpc or not addr or not identity_addr:
        return 0.0, 0.0
    try:
        w3       = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 4}))
        identity = w3.eth.contract(
            address=Web3.to_checksum_address(identity_addr), abi=_IDENTITY_ABI
        )
        token_id = identity.functions.getCurrentTokenId(agent_id).call()
        c        = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_MODE_SCORES_ABI)
        solo_total = c.functions._agentSoloTotal(token_id).call()
        solo_count = c.functions._agentSoloCount(token_id).call()
        pipe_total = c.functions._agentPipelineTotal(token_id).call()
        pipe_count = c.functions._agentPipelineCount(token_id).call()
        mean_solo     = (solo_total / solo_count)     if solo_count     else 0.0
        mean_pipeline = (pipe_total / pipe_count)     if pipe_count     else 0.0
        return float(mean_solo), float(mean_pipeline)
    except Exception as exc:
        logger.warning("Mode scores RPC failed for %s: %s", agent_id, exc)
        return 0.0, 0.0


def get_starred_signals(token_id: int) -> list[dict]:
    """Return only starred feedback signals for f[i] computation."""
    raw = _get_rep_events(token_id)
    return [
        {
            "value":          e.get("value", 0),
            "value_decimals": e.get("valueDecimals", 0),
        }
        for e in raw
        if e.get("tag1") == "starred"
    ]




def compute_C_uplift(agent_id: str) -> float:
    """
    ATE uplift pipeline vs solo — direct RPC.
    uplift = max(mean_pipeline - mean_solo, 0) / 100
    """
    mean_solo, mean_pipeline = _get_mode_scores(agent_id)
    if mean_solo == 0.0 and mean_pipeline == 0.0:
        return 0.0
    uplift = mean_pipeline - mean_solo
    return max(uplift, 0.0) / 100.0


def build_C_matrix(agent_ids: list[str]) -> np.ndarray:
    """
    Matrice C via direct RPC — ValidationRegistry.getAgentModeScores().
    C[j][i] = uplift[j] / K  pour i ≠ j ayant des scores pipeline.
    """
    N = len(agent_ids)
    C = np.zeros((N, N))
    if N <= 1:
        return C

    uplifts     = [compute_C_uplift(aid) for aid in agent_ids]
    has_pipeline = []
    for aid in agent_ids:
        _, mean_pipeline = _get_mode_scores(aid)
        has_pipeline.append(mean_pipeline > 0.0)

    for j, uplift in enumerate(uplifts):
        if uplift > 0.0:
            eligible = [i for i in range(N) if i != j and has_pipeline[i]]
            if not eligible:
                eligible = [i for i in range(N) if i != j]
            share = uplift / len(eligible)
            for i in eligible:
                C[j][i] = share
    return C


def eigentrust_iterate(
    p:        np.ndarray,
    C:        np.ndarray,
    alpha:    float = ALPHA,
    max_iter: int   = MAX_ITER,
    epsilon:  float = EPSILON,
) -> tuple[np.ndarray, int, bool]:
    t = p.copy()
    converged = False
    iters = 0
    for iters in range(1, max_iter + 1):
        t_new = (1.0 - alpha) * (C.T @ t) + alpha * p
        s = t_new.sum()
        if s > 0:
            t_new /= s
        delta = float(np.abs(t_new - t).sum())
        t = t_new
        if delta < epsilon:
            converged = True
            break
    return t, iters, converged


def compute_eigentrust(
    agents:           list[dict],
    task_p_overrides: dict[str, float],
    alpha:            float = ALPHA,
) -> EigenTrustResult:
    """
    Calcule EigenTrust pour la liste d'agents.

    agents           : [{"agent_id": str, "token_id": int}]
    task_p_overrides : {agent_id: score_0_100} — OBLIGATOIRE, source = blockchain receipt.

    p[i] vient exclusivement de task_p_overrides.
    C[j][i] vient de direct RPC getAgentModeScores().
    f[i] vient de The Graph starred signals.
    """
    N = len(agents)
    if N == 0:
        return EigenTrustResult([], [], [], [], [], [], 0, True, {})

    agent_ids = [a["agent_id"] for a in agents]
    token_ids = [a.get("token_id", 0) for a in agents]

    # ── p[i] — exclusivement depuis task_p_overrides ────────────────────────
    success_rates = np.zeros(N)
    for i, agent in enumerate(agents):
        aid = agent["agent_id"]
        if aid in task_p_overrides:
            success_rates[i] = max(0.0, float(task_p_overrides[aid]))

    p_sum = success_rates.sum()
    if p_sum == 0:
        zero_scores = {
            agent_ids[i]: {"pre_trust": 0.0, "global_trust": 0.0,
                           "user_feedback": 0.0, "final_score": 0.0}
            for i in range(N)
        }
        return EigenTrustResult(
            agent_ids=agent_ids, token_ids=token_ids,
            pre_trust=[0.0]*N, global_trust=[0.0]*N,
            final_scores=[0.0]*N, user_feedback=[0.0]*N,
            iterations=0, converged=True, scores_by_agent=zero_scores,
        )
    p = success_rates / p_sum

    # ── f[i] — starred feedback depuis The Graph ─────────────────────────────
    uf_sums   = np.zeros(N)
    uf_counts = np.zeros(N)
    for i, agent in enumerate(agents):
        tid = agent.get("token_id", 0)
        if tid:
            for sig in get_starred_signals(tid):
                dec = sig["value_decimals"] or 0
                val = int(sig["value"]) / (10 ** dec) if dec else float(sig["value"])
                uf_sums[i]   += max(0.0, val)
                uf_counts[i] += 1

    uf_avg = np.where(uf_counts > 0, np.divide(uf_sums, uf_counts, where=uf_counts > 0, out=np.zeros(N)), 0.0)
    uf     = uf_avg / 100.0
    uf     = np.where(uf > 0, uf, 0.5)

    # ── C — direct RPC getAgentModeScores() ──────────────────────────────────
    C = build_C_matrix(agent_ids)
    if C.sum() == 0:
        C = np.eye(N) / N

    # ── Power Method ─────────────────────────────────────────────────────────
    t, iters, converged = eigentrust_iterate(p, C, alpha)
    logger.info("EigenTrust: N=%d iters=%d converged=%s", N, iters, converged)

    # ── V[i] = t[i] × f[i] ───────────────────────────────────────────────────
    final = t * uf
    fs = final.sum()
    if fs > 0:
        final /= fs

    scores_by_agent = {
        agent_ids[i]: {
            "pre_trust":     round(float(p[i]),        6),
            "global_trust":  round(float(t[i]),         6),
            "user_feedback": round(float(uf[i]),        4),
            "final_score":   round(float(final[i]),     6),
        }
        for i in range(N)
    }

    return EigenTrustResult(
        agent_ids=agent_ids, token_ids=token_ids,
        pre_trust=p.tolist(), global_trust=t.tolist(),
        final_scores=final.tolist(), user_feedback=uf.tolist(),
        iterations=iters, converged=converged,
        scores_by_agent=scores_by_agent,
    )



"""
eigentrust_service.py — OpenRank EigenTrust Engine.

Architecture 4 phases (OpenRank) :

  Phase 1 — Ingestion
    p[i]    = SuccessRate normalisé de l'agent i  (Judge → Agent, ancre technique)
    C[i][j] = Score de collaboration Agent i → Agent j  (Agent → Agent, propagation)

  Phase 2 — Moteur (Power Method)
    t^(k+1) = (1 - α) × Cᵀ × t^(k) + α × p
    Convergence : ||t^(k+1) - t^k||₁ < ε

  Phase 3 — Global-Trust
    t_i = score de réputation technique absolu

  Phase 4 — Score Final (couche applicative)
    score_final_i = t_i × user_feedback_normalized_i
    (User → Agent = pondérateur contextuel, pas input EigenTrust)

Références :
  Kamvar et al., "The EigenTrust Algorithm for Reputation Management in P2P Networks",
  Stanford / WWW 2003.
  OpenRank Protocol — contextual trust scoring.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.db.reputation_repo import get_reputation_signals

logger = logging.getLogger(__name__)

# ── Hyperparamètres ────────────────────────────────────────────────────────────
ALPHA      = 0.15   # poids du pre-trust (juge) vs local-trust (collaborations)
MAX_ITER   = 100    # itérations max Power Method
EPSILON    = 1e-6   # seuil de convergence


@dataclass
class EigenTrustResult:
    """Résultat complet du calcul EigenTrust pour un ensemble d'agents."""
    agent_ids:    list[str]            # ordre des agents dans les vecteurs
    token_ids:    list[int]
    pre_trust:    list[float]          # p — vecteur ancre (SuccessRate normalisé)
    global_trust: list[float]          # t — score EigenTrust final
    final_scores: list[float]          # t × user_feedback
    user_feedback: list[float]         # starred normalisé
    iterations:   int                  # nombre d'itérations jusqu'à convergence
    converged:    bool
    scores_by_agent: dict[str, dict] = field(default_factory=dict)


def compute_eigentrust(
    agents: list[dict],
    collaboration_matrix: Optional[dict[str, dict[str, float]]] = None,
    alpha: float = ALPHA,
) -> EigenTrustResult:
    """
    Calcule les scores EigenTrust pour une liste d'agents.

    agents : liste de { agent_id, token_id } — tous les agents actifs
    collaboration_matrix : { agent_id_i: { agent_id_j: score } }
                           Vide pour l'instant (Phase 3 Planner le remplira).
    """
    N = len(agents)
    if N == 0:
        return EigenTrustResult([], [], [], [], [], [], 0, True, {})

    agent_ids = [a["agent_id"] for a in agents]
    token_ids = [a["token_id"] for a in agents]
    idx       = {aid: i for i, aid in enumerate(agent_ids)}

    # ── Phase 1 : Construire p (pre-trust = SuccessRate des juges) ─────────────

    success_rates = np.zeros(N)
    user_feedbacks = np.zeros(N)

    for i, agent in enumerate(agents):
        signals = get_reputation_signals(agent["token_id"])
        for sig in signals:
            if sig["tag1"] == "successRate":
                # value ∈ [0, 100], valueDecimals=0
                val = sig["value"] / (10 ** sig["value_decimals"]) if sig["value_decimals"] else sig["value"]
                success_rates[i] += max(0.0, float(val))
            elif sig["tag1"] == "starred":
                # value ∈ [20, 100] (score×20), on accumule pour moyenne
                val = sig["value"] / (10 ** sig["value_decimals"]) if sig["value_decimals"] else sig["value"]
                user_feedbacks[i] += max(0.0, float(val))

    # Normaliser p → somme = 1  (si tous à zéro, distribution uniforme)
    p_sum = success_rates.sum()
    if p_sum > 0:
        p = success_rates / p_sum
    else:
        p = np.ones(N) / N   # fallback uniforme si aucun verdict juge

    # Normaliser user_feedback → [0, 1]
    uf_max = user_feedbacks.max()
    if uf_max > 0:
        uf_normalized = user_feedbacks / uf_max
    else:
        uf_normalized = np.ones(N)   # pas de notes → multiplier par 1 (neutre)

    # ── Phase 1 : Construire C (local-trust = collaborations Agent→Agent) ──────

    C = np.zeros((N, N))

    if collaboration_matrix:
        for agent_i, partners in collaboration_matrix.items():
            i = idx.get(agent_i)
            if i is None:
                continue
            row_sum = sum(v for v in partners.values() if v > 0)
            if row_sum == 0:
                continue
            for agent_j, score in partners.items():
                j = idx.get(agent_j)
                if j is not None and score > 0:
                    C[i][j] = score / row_sum

    # Si C est vide (pas encore de collaborations), utiliser identité normalisée
    # → chaque agent se fait confiance à lui-même (neutre, n'influence pas EigenTrust)
    if C.sum() == 0:
        C = np.eye(N) / N if N > 0 else C

    # Normaliser les lignes de C (chaque ligne = distribution de confiance sortante)
    row_sums = C.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1   # éviter division par zéro
    C = C / row_sums

    # ── Phase 2 : Power Method ─────────────────────────────────────────────────
    #
    #   t^(k+1) = (1 - α) × Cᵀ × t^(k) + α × p
    #

    t = p.copy()   # initialisation avec pre-trust
    converged = False
    iters = 0

    for iters in range(1, MAX_ITER + 1):
        t_new = (1 - alpha) * (C.T @ t) + alpha * p
        # Renormaliser pour stabilité numérique
        t_new_sum = t_new.sum()
        if t_new_sum > 0:
            t_new = t_new / t_new_sum
        delta = np.abs(t_new - t).sum()
        t = t_new
        if delta < EPSILON:
            converged = True
            break

    logger.info(
        "EigenTrust: N=%d iterations=%d converged=%s alpha=%.2f",
        N, iters, converged, alpha,
    )

    # ── Phase 3 : Global-Trust (t = résultat brut) ─────────────────────────────

    global_trust = t.tolist()

    # ── Phase 4 : Score Final = GlobalTrust × UserFeedback ────────────────────

    final = t * uf_normalized
    final_sum = final.sum()
    if final_sum > 0:
        final = final / final_sum   # renormaliser pour garder somme=1

    final_scores  = final.tolist()
    uf_normalized_list = uf_normalized.tolist()

    # ── Résumé par agent ───────────────────────────────────────────────────────

    scores_by_agent = {
        agent_ids[i]: {
            "pre_trust":      round(p[i], 6),
            "global_trust":   round(global_trust[i], 6),
            "user_feedback":  round(uf_normalized_list[i], 4),
            "final_score":    round(final_scores[i], 6),
        }
        for i in range(N)
    }

    return EigenTrustResult(
        agent_ids=agent_ids,
        token_ids=token_ids,
        pre_trust=p.tolist(),
        global_trust=global_trust,
        final_scores=final_scores,
        user_feedback=uf_normalized_list,
        iterations=iters,
        converged=converged,
        scores_by_agent=scores_by_agent,
    )

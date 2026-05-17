"""
eigentrust_service.py — OpenRank EigenTrust Engine (Étape 2 complète).

FORMULES IMPLÉMENTÉES
─────────────────────────────────────────────────────────────────────────────
1. Seed Trust  p[i]                                      (Formule de base)
   ─────────────────────────────────────────────────────
   Scores juges = [judge_alpha, judge_beta, judge_gamma]   ∈ [0, 100]

   p[i] = mean(judge_scores)     — juges UNIQUEMENT, indépendant de tout autre agent.
   user_feedback n'entre PAS dans p. Il alimente f[i] (couche applicative séparée).

   Normalisé avant Power Method : p̂ = p / sum(p)  (si sum>0, sinon uniforme)

   Source DB : tag1="successRate" dans reputation_events (écrit par indexeur).
   Pour une tâche fraîche : task_p_overrides={agent_id: valeur_0_100} bypasse DB.

2. Collaboration Capacity  C[j][i]                        (ATE — Imbens 2021)
   ─────────────────────────────────────────────────────
   uplift[j] = max( mean(pipeline_scores[j]) − mean(solo_scores[j]), 0 ) / 100

   C[j][i] = uplift[j] / (N − 1)   pour i ≠ j     (crédit distribué équitable)
   C[j][j] = 0                                      (pas d'auto-confiance)

   Source DB : collaboration_log (mode=0 solo, mode=1 pipeline)
   Écrit par blockchain_indexer via ScoreRecorded event.

   Interprétation : si B se comporte mieux en pipeline qu'en solo, B distribue
   ce crédit à tous les autres agents (dont A qui l'a alimenté en upstream).

3. Power Method                                           (Kamvar et al. 2003)
   ─────────────────────────────────────────────────────
   t⁽⁰⁾ = p̂
   t⁽ᵏ⁺¹⁾ = (1 − α) · Cᵀ · t⁽ᵏ⁾ + α · p̂     (renormalisé à chaque étape)
   convergence : ‖t⁽ᵏ⁺¹⁾ − t⁽ᵏ⁾‖₁ < ε

   α = 0.15 (poids du pre-trust vs propagation collaboration)

4. Score Final  V[i]                                      (OpenRank, couche app)
   ─────────────────────────────────────────────────────
   V[i] = t[i] × f[i]
   f[i] = moyenne glissante user_feedback normalisée max=1
   Source DB : tag1="starred" dans reputation_events.

HYPERPARAMÈTRES
   ALPHA    = 0.15    poids ancre pre-trust
   MAX_ITER = 100     itérations Power Method
   EPSILON  = 1e-6    seuil convergence ‖Δt‖₁

FLUX DE DONNÉES
   p  ←  reputation_events (tag1="successRate")  ou task_p_overrides (frais)
   C  ←  collaboration_log (solo + pipeline via ScoreRecorded)
   f  ←  reputation_events (tag1="starred")
   t  ←  Power Method sur (p, C)
   V  ←  t × f  (normalisé)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.db.collaboration_repo import get_pipeline_scores, get_solo_scores
from app.db.reputation_repo import get_reputation_signals

logger = logging.getLogger(__name__)

# ── Hyperparamètres ────────────────────────────────────────────────────────────
ALPHA    = 0.15
MAX_ITER = 100
EPSILON  = 1e-6


# ── Dataclass résultat ─────────────────────────────────────────────────────────

@dataclass
class EigenTrustResult:
    """Résultat complet du calcul EigenTrust pour un ensemble d'agents."""
    agent_ids:       list[str]
    token_ids:       list[int]
    pre_trust:       list[float]   # p̂ normalisé
    global_trust:    list[float]   # t (Power Method)
    final_scores:    list[float]   # V = t × f (normalisé)
    user_feedback:   list[float]   # f normalisé [0, 1]
    iterations:      int
    converged:       bool
    scores_by_agent: dict[str, dict] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
#  FORMULE 1 — Seed Trust p[i]
# ══════════════════════════════════════════════════════════════════════════════

def compute_p_from_scores(judge_scores: list[float]) -> float:
    """
    p[i] pour UN agent sur UNE tâche = mean(judge_scores).

    Juges UNIQUEMENT — le user_feedback n'entre pas dans p.
    Il alimente f[i] (tag1="starred" dans reputation_events) séparément.

    Retourne une valeur ∈ [0, 100].
    """
    if not judge_scores:
        return 0.0
    return float(np.mean(judge_scores))


# ══════════════════════════════════════════════════════════════════════════════
#  FORMULE 2 — Collaboration Capacity C[j][i] via ATE
# ══════════════════════════════════════════════════════════════════════════════

def compute_C_uplift(agent_id: str) -> float:
    """
    ATE (Average Treatment Effect) — performance uplift pipeline vs solo.

    uplift = max( mean(pipeline_scores) − mean(solo_scores), 0 ) / 100

    Retourne 0.0 si l'agent n'a pas assez d'historique dans les deux modes.
    Valeur ∈ [0, 1].
    """
    pipeline = [s for s in (get_pipeline_scores(agent_id) or []) if s > 0]
    solo     = [s for s in (get_solo_scores(agent_id) or []) if s > 0]
    if not pipeline or not solo:
        return 0.0
    uplift = float(np.mean(pipeline)) - float(np.mean(solo))
    return max(uplift, 0.0) / 100.0


def build_C_matrix(agent_ids: list[str]) -> np.ndarray:
    """
    Construit la matrice locale-trust C de taille N×N.

    Pour chaque agent j avec un uplift pipeline > 0 :
      C[j][i] = uplift[j] / K   pour i ≠ j ET i a au moins 1 score pipeline
      C[j][j] = 0

    Le crédit va UNIQUEMENT aux agents qui ont réellement tourné en pipeline.
    Un agent sans historique pipeline (ex: nouveau, jamais utilisé en pipeline)
    ne reçoit pas de crédit passif d'autres agents.
    """
    N = len(agent_ids)
    C = np.zeros((N, N))
    if N <= 1:
        return C
    has_pipeline = [bool(get_pipeline_scores(aid)) for aid in agent_ids]
    uplifts = [compute_C_uplift(aid) for aid in agent_ids]
    for j, uplift in enumerate(uplifts):
        if uplift > 0.0:
            eligible = [i for i in range(N) if i != j and has_pipeline[i]]
            if not eligible:
                eligible = [i for i in range(N) if i != j]
            share = uplift / len(eligible)
            for i in eligible:
                C[j][i] = share
    return C


# ══════════════════════════════════════════════════════════════════════════════
#  FORMULE 3 — Power Method (Kamvar 2003)
# ══════════════════════════════════════════════════════════════════════════════

def eigentrust_iterate(
    p:        np.ndarray,
    C:        np.ndarray,
    alpha:    float = ALPHA,
    max_iter: int   = MAX_ITER,
    epsilon:  float = EPSILON,
) -> tuple[np.ndarray, int, bool]:
    """
    t⁽⁰⁾ = p
    t⁽ᵏ⁺¹⁾ = (1 − α) · Cᵀ · t⁽ᵏ⁾ + α · p     renormalisé

    Retourne (t, iterations, converged).
    """
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


# ══════════════════════════════════════════════════════════════════════════════
#  FONCTION PRINCIPALE — compute_eigentrust
# ══════════════════════════════════════════════════════════════════════════════

def compute_eigentrust(
    agents:            list[dict],
    task_p_overrides:  Optional[dict[str, float]] = None,
    alpha:             float = ALPHA,
) -> EigenTrustResult:
    """
    Calcule EigenTrust pour la liste d'agents.

    agents           : [{"agent_id": str, "token_id": int}]
    task_p_overrides : {agent_id: valeur_0_100} — override p frais après une tâche.
                       Pour les agents non-overridés, p vient de tag1="successRate" (DB).

    Flux interne :
      1. Lire signals DB (successRate + starred) pour chaque agent.
      2. Appliquer task_p_overrides si fourni.
      3. Construire C via build_C_matrix (collaboration_log ATE).
      4. Lancer eigentrust_iterate (Power Method).
      5. Calculer V[i] = t[i] × f[i] (score final).
    """
    N = len(agents)
    if N == 0:
        return EigenTrustResult([], [], [], [], [], [], 0, True, {})

    # ── Cas spécial N=1 : scores absolus (relatifs sans sens avec 1 seul agent) ──
    if N == 1:
        aid = agents[0]["agent_id"]
        tid = agents[0].get("token_id", 0)
        raw_score = 0.0
        if task_p_overrides and aid in task_p_overrides:
            raw_score = max(0.0, float(task_p_overrides[aid]))
        else:
            # Try collaboration_log (solo, then pipeline — both are real judge scores)
            scores = get_solo_scores(aid) or get_pipeline_scores(aid)
            if scores:
                nonzero = [s for s in scores if s > 0]
                recent  = nonzero[-5:] if nonzero else []
                raw_score = max(0.0, sum(recent) / len(recent)) if recent else 0.0
        starred_vals = []
        signals = get_reputation_signals(tid) if tid else []
        for sig in signals:
            dec = sig["value_decimals"] or 0
            val = sig["value"] / (10 ** dec) if dec else float(sig["value"])
            if sig["tag1"] == "starred":
                starred_vals.append(max(0.0, val))
        raw_uf   = (sum(starred_vals) / len(starred_vals)) if starred_vals else 0.0
        p_val    = raw_score / 100.0
        uf_val   = raw_uf / 100.0 if raw_uf > 0 else 0.5
        final_val = p_val * uf_val
        score_entry = {
            "pre_trust":     round(p_val,     6),
            "global_trust":  round(p_val,     6),
            "user_feedback": round(uf_val,    4),
            "final_score":   round(final_val, 6),
        }
        return EigenTrustResult(
            agent_ids=[aid],
            token_ids=[tid],
            pre_trust=[p_val],
            global_trust=[p_val],
            final_scores=[final_val],
            user_feedback=[uf_val],
            iterations=0,
            converged=True,
            scores_by_agent={aid: score_entry},
        )

    agent_ids = [a["agent_id"] for a in agents]
    token_ids = [a.get("token_id", 0) for a in agents]

    success_rates  = np.zeros(N)
    uf_sums        = np.zeros(N)
    uf_counts      = np.zeros(N)

    for i, agent in enumerate(agents):
        aid = agent["agent_id"]
        tid = agent.get("token_id", 0)

        signals = get_reputation_signals(tid) if tid else []
        for sig in signals:
            dec = sig["value_decimals"] or 0
            val = sig["value"] / (10 ** dec) if dec else float(sig["value"])
            if sig["tag1"] == "successRate":
                success_rates[i] += max(0.0, val)
            elif sig["tag1"] == "starred":
                uf_sums[i]   += max(0.0, val)
                uf_counts[i] += 1

        if task_p_overrides and aid in task_p_overrides:
            success_rates[i] = max(0.0, float(task_p_overrides[aid]))

    # ── Normaliser p ──────────────────────────────────────────────────────────
    p_sum = success_rates.sum()
    p = success_rates / p_sum if p_sum > 0 else np.ones(N) / N

    # ── Normaliser f (user_feedback) → [0, 1] — moyenne des étoiles / 100 ──────
    # Moyenne (pas somme) pour qu'un agent avec N avis garde la même valeur.
    # Fallback 0.5 si aucun feedback → neutre.
    uf_avg = np.where(uf_counts > 0, uf_sums / uf_counts, 0.0)
    uf = uf_avg / 100.0
    uf = np.where(uf > 0, uf, 0.5)  # agents sans feedback → 0.5 (neutre)

    # ── Construire C (ATE depuis collaboration_log) ───────────────────────────
    C = build_C_matrix(agent_ids)

    # Fallback si aucune collaboration → identité normalisée (t converge vers p)
    if C.sum() == 0:
        C = np.eye(N) / N

    # ── Power Method ─────────────────────────────────────────────────────────
    t, iters, converged = eigentrust_iterate(p, C, alpha)

    logger.info(
        "EigenTrust: N=%d iters=%d converged=%s alpha=%.2f",
        N, iters, converged, alpha,
    )

    # ── Score Final V[i] = t[i] × f[i] ───────────────────────────────────────
    final = t * uf
    fs = final.sum()
    if fs > 0:
        final /= fs

    global_trust_list = t.tolist()
    final_scores_list = final.tolist()
    uf_list           = uf.tolist()

    scores_by_agent = {
        agent_ids[i]: {
            "pre_trust":    round(float(p[i]),                 6),
            "global_trust": round(float(global_trust_list[i]), 6),
            "user_feedback": round(float(uf_list[i]),          4),
            "final_score":  round(float(final_scores_list[i]), 6),
        }
        for i in range(N)
    }

    return EigenTrustResult(
        agent_ids=agent_ids,
        token_ids=token_ids,
        pre_trust=p.tolist(),
        global_trust=global_trust_list,
        final_scores=final_scores_list,
        user_feedback=uf_list,
        iterations=iters,
        converged=converged,
        scores_by_agent=scores_by_agent,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  FONCTIONS DE WORKFLOW (appelées après validation)
# ══════════════════════════════════════════════════════════════════════════════

def process_solo_task(
    agent_id:     str,
    judge_scores: list[float],
    agents:       Optional[list[dict]] = None,
) -> EigenTrustResult:
    """
    Workflow tâche SOLO (mode=0) :
      1. Calcule p[agent_id] = mean(judge_scores)   — juges uniquement
      2. Lance EigenTrust global avec ce p frais comme override.

    user_feedback → va dans f[i] via reputation_events (tag1="starred"),
                    PAS dans p[i].

    Note : l'écriture dans collaboration_log (mode=0) est faite en parallèle
           par blockchain_indexer via ScoreRecorded event — PAS ici.

    agents : si None, chargé depuis identity_repo (tous agents enregistrés).
    """
    p_value = compute_p_from_scores(judge_scores)
    if agents is None:
        from app.db.identity_repo import get_all_agent_identities
        rows   = get_all_agent_identities()
        agents = [
            {"agent_id": r["agent_id"], "token_id": r["current_token_id"]}
            for r in rows if r.get("current_token_id")
        ]
    logger.info("process_solo_task: agent=%s p=%.2f", agent_id, p_value)
    return compute_eigentrust(agents, task_p_overrides={agent_id: p_value})


def process_pipeline_task(
    pipeline: list[dict],
    agents:   Optional[list[dict]] = None,
) -> EigenTrustResult:
    """
    Workflow tâche PIPELINE (mode=1) :
      1. Calcule p[i] pour chaque agent du pipeline.
      2. Lance EigenTrust global avec ces p frais comme overrides.

    pipeline : [{"agent_id": str, "judge_scores": list[float]}]
               p[i] = mean(judge_scores[i]) pour chaque agent — juges uniquement.
               user_feedback → va dans f[i] via reputation_events (tag1="starred").

    Note : l'écriture dans collaboration_log (mode=1) est faite par
           blockchain_indexer via ScoreRecorded — PAS ici.
    """
    overrides = {
        entry["agent_id"]: compute_p_from_scores(entry["judge_scores"])
        for entry in pipeline
    }
    if agents is None:
        from app.db.identity_repo import get_all_agent_identities
        rows   = get_all_agent_identities()
        agents = [
            {"agent_id": r["agent_id"], "token_id": r["current_token_id"]}
            for r in rows if r.get("current_token_id")
        ]
    logger.info(
        "process_pipeline_task: %d agents, overrides=%s",
        len(pipeline), {k: round(v, 1) for k, v in overrides.items()},
    )
    return compute_eigentrust(agents, task_p_overrides=overrides)

"""
matching_service.py — Matching sémantique SubTask → Agent.

Algorithme :
  score(agent, subtask) = 0.6 × cosine_sim(embed(subtask.desc), agent.embedding)
                        + 0.4 × eigentrust[agent.global_trust]

Embedding : BAAI/bge-m3 via FlagEmbedding (multilingual, 1024 dims).
Chargement du modèle : lazy, une seule fois au premier appel (singleton).

Flux :
  1. embed_agent_capabilities(agent_id, identity_metadata) — appelé à l'enregistrement
     → calcule le vecteur de l'agent et le stocke dans agents.capability_embedding
  2. select_agents(subtasks, trust_scores) — appelé par execution_service
     → pour chaque subtask, retourne le meilleur agent disponible
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from os import environ
from typing import Optional

import numpy as np

from app.db.database import get_connection
from app.services.planner_service import SubTask

logger = logging.getLogger(__name__)

COSINE_WEIGHT    = 0.6
EIGENTRUST_WEIGHT = 0.4

# ── Singleton modèle BAAI/bge-m3 (FlagEmbedding) ─────────────────────────────
# SentenceTransformer appelle os._exit() depuis un thread pool sur Windows —
# FlagEmbedding charge le même modèle sans ce problème.
_model = None
_model_lock = threading.RLock()


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
        from FlagEmbedding import FlagModel
        try:
            import torch
            use_cuda = bool(torch.cuda.is_available())
        except Exception:
            use_cuda = False
        device = "cuda" if use_cuda else "cpu"
        logger.info("Chargement BAAI/bge-m3 via FlagEmbedding…")
        _model = FlagModel("BAAI/bge-m3", use_fp16=use_cuda, device=device)
        logger.info("BAAI/bge-m3 chargé ✓")
        return _model


# ── Embedding ─────────────────────────────────────────────────────────────────

def compute_embedding(text: str) -> list[float]:
    """Calcule le vecteur dense BAAI/bge-m3 pour un texte."""
    model = _get_model()
    with _model_lock:
        raw = model.encode([text])   # shape (1, dim)
    vec = np.array(raw[0], dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# ── Représentation texte d'un agent pour l'embedding ─────────────────────────

def _agent_text(identity_metadata: dict) -> str:
    """
    Construit le texte représentatif d'un agent (provider ou juge) pour l'embedding.
    Provider : name + description + services.skills + capabilities.supported_tasks
    Juge     : + evaluation_skills + validated_task_types + evaluation_domains
               + tools_used + evaluation_style
    """
    parts = [
        identity_metadata.get("name", ""),
        identity_metadata.get("description", ""),
    ]
    for svc in identity_metadata.get("services", []):
        parts.extend(svc.get("skills", []))
    caps = identity_metadata.get("capabilities", {})
    parts.extend(caps.get("supported_tasks", []))
    parts.extend(caps.get("special_caps", []))
    # Judge-specific top-level fields
    parts.extend(identity_metadata.get("evaluation_skills", []))
    parts.extend(identity_metadata.get("validated_task_types", []))
    parts.extend(identity_metadata.get("evaluation_domains", []))
    parts.extend(identity_metadata.get("tools_used", []))
    parts.extend(identity_metadata.get("special_caps", []))
    style = identity_metadata.get("evaluation_style", "")
    if style:
        parts.append(style)
    return " ".join(p for p in parts if p)


# ── Calcul + stockage embedding agent ─────────────────────────────────────────

def embed_agent_capabilities(agent_id: str, identity_metadata: dict) -> list[float]:
    """
    Calcule l'embedding de l'agent et le persiste dans agents.capability_embedding.
    Appelé une seule fois à l'enregistrement (ou à la nouvelle version).
    """
    text = _agent_text(identity_metadata)
    if not text.strip():
        logger.warning("embed_agent_capabilities: texte vide pour agent %s", agent_id)
        return []
    vec = compute_embedding(text)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE agents SET capability_embedding = ? WHERE agent_id = ?",
            (json.dumps(vec), agent_id),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Embedding stocké pour agent %s (dim=%d)", agent_id, len(vec))
    return vec


# ── Chargement agents avec embeddings ─────────────────────────────────────────

def _load_judges_with_embeddings() -> list[dict]:
    """Retourne tous les juges actifs avec leur embedding depuis DB."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT agent_id, identity_metadata, capability_embedding
            FROM agents
            WHERE status = 'active' AND agent_type = 1
            """
        ).fetchall()
        judges = []
        for row in rows:
            emb_raw = row["capability_embedding"]
            if not emb_raw:
                continue
            try:
                emb = json.loads(emb_raw)
            except Exception:
                continue
            judges.append({
                "agent_id":  row["agent_id"],
                "embedding": emb,
            })
        return judges
    finally:
        conn.close()


def _load_agents_with_embeddings() -> list[dict]:
    """Retourne tous les agents actifs providers avec leur embedding depuis DB."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT agent_id, identity_metadata, capability_embedding
            FROM agents
            WHERE status = 'active' AND agent_type != 1
            """
        ).fetchall()
        agents = []
        for row in rows:
            emb_raw = row["capability_embedding"]
            if not emb_raw:
                continue
            try:
                emb = json.loads(emb_raw)
            except Exception:
                continue
            meta_raw = row["identity_metadata"] or "{}"
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else {}
            except Exception:
                meta = {}
            agents.append({
                "agent_id":  row["agent_id"],
                "embedding": emb,
                "metadata":  meta,
            })
        return agents
    finally:
        conn.close()


# ── Dataclass résultat matching ───────────────────────────────────────────────

@dataclass
class AgentMatch:
    subtask_id:     str
    agent_id:       str
    cosine_score:   float
    trust_score:    float
    final_score:    float


# ── Matching principal ────────────────────────────────────────────────────────

def select_agents(
    subtasks:     list[SubTask],
    trust_scores: dict[str, float],
) -> list[AgentMatch]:
    """
    Pour chaque subtask, sélectionne le meilleur agent disponible.

    trust_scores : {agent_id: global_trust} depuis eigentrust_service.
    Retourne un AgentMatch par subtask (ordre = ordre des subtasks).
    """
    candidates = _load_agents_with_embeddings()
    if not candidates:
        logger.warning("Aucun agent avec embedding disponible")
        return []

    results: list[AgentMatch] = []
    assigned: set[str] = set()   # évite d'assigner 2 subtasks au même agent

    for st in subtasks:
        st_emb = compute_embedding(st.description)

        best: Optional[AgentMatch] = None
        for agent in candidates:
            aid = agent["agent_id"]
            if aid in assigned:
                continue

            cos  = cosine_similarity(st_emb, agent["embedding"])
            trust = trust_scores.get(aid, 0.0)
            score = COSINE_WEIGHT * cos + EIGENTRUST_WEIGHT * trust

            if best is None or score > best.final_score:
                best = AgentMatch(
                    subtask_id=st.id,
                    agent_id=aid,
                    cosine_score=round(cos, 4),
                    trust_score=round(trust, 4),
                    final_score=round(score, 4),
                )

        if best:
            assigned.add(best.agent_id)
            results.append(best)
            logger.info(
                "Match st=%s → agent=%s (cos=%.3f trust=%.3f final=%.3f)",
                st.id, best.agent_id, best.cosine_score, best.trust_score, best.final_score,
            )
        else:
            logger.warning("Aucun agent disponible pour subtask %s (domain=%s)", st.id, st.domain)

    return results


def select_agents_top_k(
    subtasks:     list,
    trust_scores: dict,
    k:            int = 3,
) -> list[list]:
    """
    For each subtask, returns the top-k AgentMatch candidates (no deduplication across subtasks).
    Used by pack-proposals to build multiple pack options.
    result[i] = list of up to k AgentMatch for subtasks[i].
    """
    candidates = _load_agents_with_embeddings()
    if not candidates:
        return [[] for _ in subtasks]

    result = []
    for st in subtasks:
        st_emb = compute_embedding(st.description)
        scored = []
        for agent in candidates:
            aid   = agent["agent_id"]
            cos   = cosine_similarity(st_emb, agent["embedding"])
            trust = trust_scores.get(aid, 0.0)
            score = COSINE_WEIGHT * cos + EIGENTRUST_WEIGHT * trust
            scored.append(AgentMatch(
                subtask_id=st.id,
                agent_id=aid,
                cosine_score=round(cos, 4),
                trust_score=round(trust, 4),
                final_score=round(score, 4),
            ))
        scored.sort(key=lambda x: x.final_score, reverse=True)
        result.append(scored[:k])
    return result

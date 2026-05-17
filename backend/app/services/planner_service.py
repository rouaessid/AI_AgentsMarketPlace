"""
planner_service.py — Décomposition de tâche en SubTask DAG via Groq LLM.

Flux :
  decompose_task(prompt, available_domains)
    → 1 appel Groq (llama-3.3-70b-versatile, json_mode)
    → TaskPlan { mode, subtasks: list[SubTask] avec depends_on DAG }

SubTask DAG :
  - chaque SubTask a un id unique ("st-0", "st-1", ...)
  - depends_on = liste d'ids des subtasks dont cette tâche dépend
  - subtasks indépendants (depends_on=[]) s'exécutent en parallèle
  - solo = 1 subtask, pipeline = 2+ subtasks avec dépendances possibles

Domaines supportés (injectés dynamiquement depuis les agents actifs) :
  research, code, summarize, analyze, write, translate, generate, review
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from groq import Groq

from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

GROQ_MODEL = "llama-3.3-70b-versatile"

_SYSTEM_TEMPLATE = """\
Tu es un planificateur de tâches pour un marketplace d'agents IA décentralisé.
Ton rôle : analyser une requête utilisateur et la décomposer en sous-tâches atomiques.

Domaines disponibles (agents actifs dans le réseau) :
{domains}

Agents disponibles : {n_providers} agent(s) provider(s).

Règles de décomposition :
- mode "solo"     : tâche simple, 1 seul domaine requis → 1 subtask, depends_on=[]
- mode "pipeline" : tâche complexe, plusieurs domaines ou étapes enchaînées → 2-{n_providers} subtasks maximum
- IMPORTANT : ne génère JAMAIS plus de {n_providers} subtasks — chaque subtask sera assigné à un agent différent.

Règles DAG :
- id format : "st-0", "st-1", "st-2", ...
- depends_on : liste des ids des subtasks dont la sortie est nécessaire en entrée
- subtasks sans dépendance (depends_on=[]) peuvent s'exécuter en parallèle
- output_type : "text" | "json" | "code" | "data" — format attendu de la sortie

Réponds UNIQUEMENT en JSON valide, sans texte autour :
{{
  "mode": "solo" | "pipeline",
  "reasoning": "explication courte du choix",
  "subtasks": [
    {{
      "id": "st-0",
      "domain": "<domaine parmi la liste>",
      "description": "<prompt précis à envoyer à cet agent>",
      "depends_on": [],
      "output_type": "text"
    }}
  ]
}}
"""


@dataclass
class SubTask:
    id:          str
    domain:      str
    description: str
    depends_on:  list[str] = field(default_factory=list)
    output_type: str = "text"


@dataclass
class TaskPlan:
    mode:       Literal["solo", "pipeline"]
    subtasks:   list[SubTask]
    reasoning:  str
    pack_name:  str = ""
    pack_rationale: str = ""


def _get_available_domains() -> list[str]:
    """Lit les domaines disponibles depuis les skills des agents actifs en DB."""
    try:
        from app.db.identity_repo import get_all_agent_identities
        rows    = get_all_agent_identities()
        domains: set[str] = set()
        for row in rows:
            if row.get("agent_type", 0) == 1:   # skip judges
                continue
            meta_raw = row.get("identity_metadata") or "{}"
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
            except Exception:
                continue
            for svc in meta.get("services", []):
                for skill in svc.get("skills", []):
                    domains.add(skill.lower())
        return sorted(domains) if domains else ["research", "code", "summarize", "analyze", "write"]
    except Exception as e:
        logger.warning("Impossible de charger les domaines depuis DB : %s", e)
        return ["research", "code", "summarize", "analyze", "write"]


def _get_agents_info() -> tuple[int, str]:
    """Retourne (nombre, description textuelle) des providers actifs pour le prompt LLM."""
    try:
        from app.db.database import get_connection
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT agent_id, identity_metadata FROM agents "
                "WHERE status='active' AND agent_type != 1"
            ).fetchall()
            lines = []
            for row in rows:
                meta = {}
                if row["identity_metadata"]:
                    try:
                        meta = json.loads(row["identity_metadata"])
                    except Exception:
                        pass
                name  = meta.get("name") or row["agent_id"]
                tasks = []
                for svc in meta.get("services", []):
                    tasks.extend(svc.get("skills", []))
                if not tasks:
                    tasks = meta.get("capabilities", {}).get("supported_tasks", [])
                desc = ", ".join(tasks[:6]) if tasks else "agent généraliste"
                lines.append(f"- {name} (id={row['agent_id']}): {desc}")
            return len(rows), "\n".join(lines) if lines else "3 agents (researcher, analyst, writer)"
        finally:
            conn.close()
    except Exception:
        return 3, "- ResearchBot (id=researcher-01): research, analyze\n- AnalystBot (id=analyst-01): analyze, summarize\n- WriterBot (id=writer-01): write, draft, report"


def _get_provider_count() -> int:
    """Retourne le nombre de providers actifs (agents non-juges)."""
    try:
        from app.db.database import get_connection
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM agents WHERE status='active' AND agent_type != 1"
            ).fetchone()
            return max(1, row[0]) if row else 3
        finally:
            conn.close()
    except Exception:
        return 3


_ALTERNATIVES_SYSTEM = """\
Tu es un planificateur pour un marketplace d'agents IA décentralisé.
Ta mission : proposer toutes les approches PERTINENTES et DISTINCTES pour accomplir la tâche.

Agents disponibles sur la plateforme :
{agents_info}

Domaines disponibles : {domains}

Règles :
- Propose autant d'approches que pertinent — ni plus, ni moins.
- Chaque approche doit être DISTINCTEMENT DIFFÉRENTE : nombre d'agents différent, ou spécialisation différente.
- 1 agent seul : si un seul peut couvrir toute la tâche efficacement (plus rapide, moins cher)
- 2 agents : si 2 spécialisations apportent une vraie valeur ajoutée
- 3 agents ou plus : si la tâche est complexe et justifie un pipeline complet
- N'utilise QUE les agents listés ci-dessus (utilise leur agent_id exact).
- Ne propose PAS d'approches qui sont de simples permutations des mêmes agents.

Pour chaque subtask, "description" doit être un prompt complet et précis à envoyer à l'agent.
Pour chaque subtask, "domain" doit être un des domaines disponibles listés.

Réponds UNIQUEMENT en JSON valide :
{{
  "plans": [
    {{
      "pack_name": "Nom court et expressif (ex: 'Recherche rapide', 'Pipeline complet')",
      "pack_rationale": "Pourquoi cette approche est adaptée à cette tâche spécifique",
      "mode": "solo",
      "subtasks": [
        {{
          "id": "st-0",
          "domain": "<domaine>",
          "description": "<prompt précis pour l'agent>",
          "depends_on": [],
          "output_type": "text"
        }}
      ]
    }}
  ]
}}
"""


def _parse_plan(raw: str) -> TaskPlan:
    """Parse la réponse JSON du LLM en TaskPlan."""
    data = json.loads(raw)
    subtasks = [
        SubTask(
            id=st["id"],
            domain=st["domain"],
            description=st["description"],
            depends_on=st.get("depends_on", []),
            output_type=st.get("output_type", "text"),
        )
        for st in data.get("subtasks", [])
    ]
    if not subtasks:
        raise ValueError("Le planner n'a retourné aucune subtask")

    mode = data.get("mode", "solo")
    if mode not in ("solo", "pipeline"):
        mode = "solo" if len(subtasks) == 1 else "pipeline"

    return TaskPlan(
        mode=mode,
        subtasks=subtasks,
        reasoning=data.get("reasoning", ""),
    )


def topological_levels(subtasks: list[SubTask]) -> list[list[SubTask]]:
    """
    Tri topologique → niveaux d'exécution parallèle.

    Retourne une liste de niveaux, chaque niveau contenant les subtasks
    dont toutes les dépendances sont satisfaites par les niveaux précédents.
    Permet asyncio.gather() par niveau dans execution_service.
    """
    completed: set[str] = set()
    remaining = list(subtasks)
    levels: list[list[SubTask]] = []

    while remaining:
        ready = [st for st in remaining if all(d in completed for d in st.depends_on)]
        if not ready:
            logger.error("DAG cyclique ou dépendances manquantes — exécution séquentielle forcée")
            ready = [remaining[0]]
        levels.append(ready)
        for st in ready:
            completed.add(st.id)
            remaining.remove(st)

    return levels


async def decompose_task(
    prompt:  str,
    domains: list[str] | None = None,
) -> TaskPlan:
    """
    Décompose un prompt utilisateur en TaskPlan (DAG de SubTasks).

    domains : si None, chargé automatiquement depuis les agents actifs en DB.
    """
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY non configurée")

    available   = domains or _get_available_domains()
    n_providers = _get_provider_count()
    system_prompt = _SYSTEM_TEMPLATE.format(
        domains=", ".join(available),
        n_providers=n_providers,
    )

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        response_format={"type": "json_object"},
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt},
        ],
    )

    raw = response.choices[0].message.content or ""
    logger.info("Planner raw response: %s", raw[:200])

    try:
        plan = _parse_plan(raw)
    except Exception as e:
        logger.error("Planner parse error: %s — raw: %s", e, raw[:300])
        plan = TaskPlan(
            mode="solo",
            subtasks=[SubTask(id="st-0", domain=available[0], description=prompt)],
            reasoning=f"Fallback solo (parse error: {e})",
        )

    logger.info(
        "TaskPlan: mode=%s subtasks=%d reasoning=%s",
        plan.mode, len(plan.subtasks), plan.reasoning[:80],
    )
    return plan


async def decompose_task_alternatives(prompt: str) -> list[TaskPlan]:
    """
    Demande au LLM de proposer N approches distinctes pour la tâche.
    Chaque plan = une vraie approche différente (pas des permutations).
    Retourne 1 à N plans selon ce qui fait sens pour la tâche.
    """
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY non configurée")

    available         = _get_available_domains()
    _, agents_info = _get_agents_info()
    system_prompt     = _ALTERNATIVES_SYSTEM.format(
        agents_info=agents_info,
        domains=", ".join(available),
    )

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        response_format={"type": "json_object"},
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt},
        ],
    )

    raw = response.choices[0].message.content or ""
    logger.info("Alternatives raw: %s", raw[:400])

    try:
        data  = json.loads(raw)
        plans: list[TaskPlan] = []
        seen_combos: list[tuple] = []

        for p in data.get("plans", []):
            subtasks = [
                SubTask(
                    id=st["id"],
                    domain=st.get("domain", available[0]),
                    description=st["description"],
                    depends_on=st.get("depends_on", []),
                    output_type=st.get("output_type", "text"),
                )
                for st in p.get("subtasks", [])
                if st.get("description")
            ]
            if not subtasks:
                continue
            # Deduplicate by (agent_ids_tuple implied by domain sequence)
            key = tuple(st.domain for st in subtasks)
            if key in seen_combos:
                continue
            seen_combos.append(key)

            mode = p.get("mode", "solo" if len(subtasks) == 1 else "pipeline")
            plans.append(TaskPlan(
                mode=mode,
                subtasks=subtasks,
                reasoning=p.get("pack_rationale", ""),
                pack_name=p.get("pack_name", f"Option {len(plans) + 1}"),
                pack_rationale=p.get("pack_rationale", ""),
            ))

        if plans:
            logger.info("decompose_task_alternatives: %d plans générés", len(plans))
            return plans
    except Exception as e:
        logger.error("decompose_task_alternatives parse error: %s — raw: %s", e, raw[:300])

    # Fallback : un seul plan standard
    fallback = await decompose_task(prompt)
    return [fallback]

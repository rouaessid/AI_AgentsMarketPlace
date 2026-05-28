"""
execution_service.py — Orchestration DAG pipeline + validation per-agent + scoring on-chain.

Flux complet :
  execute_pipeline_task(task_id, plan, matches, prompt, agent_params)
    1. Tri topologique du DAG → niveaux d'exécution parallèle
    2. Pour chaque niveau → asyncio.gather (sandbox_service par agent)
    3. Chaining : output step N = input step N+1 (via context dict)
    4. Assemblage final_output
    5. Validation per-agent (mode=1) :
         - Pour chaque step réussi : upload output IPFS → run_validation(agent_id, mode=1)
         - Chaque agent évalué indépendamment par ses propres juges sur SA sous-tâche
         - Chaque agent reçoit son propre aggregated_score → ScoreRecorded(mode=1) on-chain
    6. eigentrust_sync déclenché automatiquement par indexeur via ScoreRecorded events
         - collaboration_log (mode=1) alimente la matrice C pour chaque agent
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.db.pipeline_repo import update_pipeline_task
from app.services.matching_service import AgentMatch
from app.services.planner_service import SubTask, TaskPlan, topological_levels
from app.services.sandbox_service import SandboxInput, SandboxService

logger      = logging.getLogger(__name__)
sandbox_svc = SandboxService()


# ── Dataclasses résultats ─────────────────────────────────────────────────────

@dataclass
class PipelineStep:
    subtask_id:   str
    agent_id:     str
    input_prompt: str
    output:       str
    status:       str          # "success" | "failed" | "timeout"
    duration_sec: float = 0.0
    error:        str | None = None
    proxy_cid:    str | None = None


@dataclass
class PipelineResult:
    task_id:      str
    steps:        list[PipelineStep]
    final_output: str
    status:       str          # "success" | "partial" | "failed"
    proxy_cid:    str | None = None


# ── Construction prompt d'un step ─────────────────────────────────────────────

def _build_step_prompt(
    subtask:         SubTask,
    original_prompt: str,
    context:         dict[str, str],
) -> str:
    """
    Construit le prompt envoyé à l'agent pour un step donné.
    Injecte les outputs des dépendances + la description de la subtask.
    """
    parts = [f"Tâche : {subtask.description}"]

    upstream = [context[dep] for dep in subtask.depends_on if dep in context]
    if upstream:
        parts.append("\nContexte (résultats des étapes précédentes) :")
        for i, out in enumerate(upstream, 1):
            parts.append(f"[Étape {i}]\n{out}")

    if not subtask.depends_on:
        parts.append(f"\nRequête originale : {original_prompt}")

    return "\n\n".join(parts)


# ── Exécution d'un step individuel ────────────────────────────────────────────

async def _run_step(
    subtask:  SubTask,
    agent_id: str,
    task_id:  str,
    context:  dict[str, str],
    original_prompt: str,
    agent_params: dict = {},
) -> PipelineStep:
    """Exécute un step du pipeline via sandbox_service."""
    from app.services.agent_service import AgentService
    agent_svc = AgentService()

    prompt = _build_step_prompt(subtask, original_prompt, context)
    step_task_id = f"{task_id}-{subtask.id}"

    try:
        record = await agent_svc.get_by_agent_id(agent_id)
    except KeyError:
        logger.error("Agent %s non trouvé dans le cache — step %s ignoré", agent_id, subtask.id)
        return PipelineStep(
            subtask_id=subtask.id, agent_id=agent_id,
            input_prompt=prompt, output="", status="failed",
            error=f"Agent {agent_id} non trouvé",
        )

    inp = SandboxInput(
        task_id=step_task_id,
        agent_id=agent_id,
        task_prompt=prompt,
    )

    # Clés provider : viennent du buyer (agent_params). Fallback platform si absent.
    _env: dict = dict(agent_params or {})
    from app.core.config import get_settings as _gs
    _cfg = _gs()
    if not _env.get("GROQ_API_KEY") and _cfg.groq_api_key:
        _env["GROQ_API_KEY"] = _cfg.groq_api_key
    if not _env.get("TAVILY_API_KEY"):
        _tavily = _cfg.writer_tavily_key or _cfg.tavily_api_key or _cfg.judge_alpha_tavily_key
        if _tavily:
            _env["TAVILY_API_KEY"] = _tavily

    try:
        manifest = await sandbox_svc.run_agent(record, inp, env_vars=_env)
        raw = manifest.output or ""
        output = json.dumps(raw, ensure_ascii=False) if isinstance(raw, (dict, list)) else str(raw).strip()
        status    = "success" if manifest.status == "success" else "failed"
        error     = manifest.error
        duration  = manifest.duration_sec
        proxy_cid = manifest.proxy_cid
    except Exception as exc:
        logger.exception("Step %s agent %s erreur: %s", subtask.id, agent_id, exc)
        output, status, error, duration, proxy_cid = "", "failed", str(exc), 0.0, None

    return PipelineStep(
        subtask_id=subtask.id, agent_id=agent_id,
        input_prompt=prompt, output=output,
        status=status, duration_sec=duration, error=error,
        proxy_cid=proxy_cid,
    )


# ── Assemblage output final ───────────────────────────────────────────────────

def _assemble_output(steps: list[PipelineStep]) -> str:
    """
    Assemble les outputs de tous les steps en un output final cohérent.
    Pour un pipeline linéaire : output du dernier step réussi.
    Pour un pipeline avec steps parallèles : concat tous les outputs réussis.
    """
    successful = [s for s in steps if s.status == "success" and s.output]
    if not successful:
        return ""
    return successful[-1].output


# ── Orchestration principale ──────────────────────────────────────────────────

async def execute_pipeline_task(
    task_id:      str,
    plan:         TaskPlan,
    matches:      list[AgentMatch],
    prompt:       str,
    agent_params: dict = {},
) -> PipelineResult:
    """
    Exécute le DAG du plan pipeline.

    1. Tri topologique → niveaux parallèles
    2. Pour chaque niveau : asyncio.gather des steps
    3. Context passing entre niveaux
    4. Assemblage final_output
    5. Mise à jour pipeline_tasks en DB
    """
    match_map: dict[str, str] = {m.subtask_id: m.agent_id for m in matches}
    context:   dict[str, str] = {}
    all_steps: list[PipelineStep] = []
    failed_subtasks: set[str] = set()

    update_pipeline_task(task_id, status="executing")

    levels = topological_levels(plan.subtasks)
    logger.info(
        "execute_pipeline_task: task=%s levels=%d subtasks=%d",
        task_id, len(levels), len(plan.subtasks),
    )

    for level_idx, level in enumerate(levels):
        runnable = []
        skipped = []
        for st in level:
            agent_id = match_map.get(st.id, "")
            failed_deps = [dep for dep in st.depends_on if dep in failed_subtasks]
            if failed_deps:
                skipped.append(PipelineStep(
                    subtask_id=st.id,
                    agent_id=agent_id,
                    input_prompt="",
                    output="",
                    status="failed",
                    error=f"Skipped because dependency failed: {', '.join(failed_deps)}",
                ))
                continue
            if agent_id:
                runnable.append((st, agent_id))

        level_steps = skipped + await asyncio.gather(*[
            _run_step(
                subtask=st,
                agent_id=agent_id,
                task_id=task_id,
                context=context,
                original_prompt=prompt,
                agent_params=agent_params,
            )
            for st, agent_id in runnable
        ])

        for step in level_steps:
            all_steps.append(step)
            if step.status == "success":
                context[step.subtask_id] = step.output
            else:
                failed_subtasks.add(step.subtask_id)

        logger.info(
            "Niveau %d terminé : %d/%d steps réussis",
            level_idx,
            sum(1 for s in level_steps if s.status == "success"),
            len(level_steps),
        )

    final_output  = _assemble_output(all_steps)
    success_count = sum(1 for s in all_steps if s.status == "success")
    total         = len(all_steps)
    if success_count == total:
        status = "success"
    elif success_count > 0:
        status = "partial"
    else:
        status = "failed"

    steps_json = [
        {
            "subtask_id":   s.subtask_id,
            "agent_id":     s.agent_id,
            "status":       s.status,
            "output":       s.output,
            "duration_sec": s.duration_sec,
            "error":        s.error,
        }
        for s in all_steps
    ]
    update_pipeline_task(
        task_id,
        steps_json=steps_json,
        final_output=final_output,
        status=status if status == "failed" else "validating",
    )

    result = PipelineResult(
        task_id=task_id,
        steps=all_steps,
        final_output=final_output,
        status=status,
    )

    if status != "failed":
        await _validate_per_agent(result)

    return result


# ── Validation par agent (mode=1 pipeline) ────────────────────────────────────

async def _validate_per_agent(result: PipelineResult) -> None:
    """
    Valide chaque agent indépendamment pour sa sous-tâche (mode=1 pipeline).
    Chaque agent reçoit son propre score de juges — aucune copie du lead.
    Les scores alimentent collaboration_log (mode=1) pour la matrice C d'EigenTrust.
    """
    from app.db.access_repo import upsert_validation_session

    val_tasks: list[tuple[str, str, str]] = []   # (agent_id, val_task_id, proxy_cid)

    update_pipeline_task(result.task_id, val_task_id=f"multi-{result.task_id[:16]}")

    for step in result.steps:
        if step.status != "success" or not step.output:
            continue

        agent_id    = step.agent_id
        val_task_id = f"val-{result.task_id[:12]}-{agent_id[:8]}"

        # Use the proxy trace CID already uploaded by sandbox_service (contains full trajectory).
        proxy_cid = step.proxy_cid or f"step-{result.task_id[:8]}-{step.subtask_id}"
        if not step.proxy_cid:
            logger.warning("No proxy_cid on step %s — judges will have no trace", step.subtask_id)

        try:
            upsert_validation_session(agent_id, val_task_id=val_task_id, status="pending")
        except Exception as exc:
            logger.warning("upsert_validation_session échoué: %s", exc)

        val_tasks.append((agent_id, val_task_id, proxy_cid, step.input_prompt))
        logger.info(
            "Validation pipeline planifiée: agent=%s val_task=%s cid=%s",
            agent_id, val_task_id, proxy_cid,
        )

    if not val_tasks:
        logger.warning("Aucun step réussi à valider dans le pipeline %s", result.task_id)
        update_pipeline_task(result.task_id, status="done",
                             finished_at=datetime.now(timezone.utc).isoformat())
        return

    # All agents validated concurrently and independently.
    # Judge-level semaphore in judge_service caps simultaneous containers at 6.
    await asyncio.gather(*[
        _run_one_validation(result.task_id, agent_id, val_task_id, proxy_cid, task_desc)
        for agent_id, val_task_id, proxy_cid, task_desc in val_tasks
    ], return_exceptions=True)

    update_pipeline_task(
        result.task_id,
        status="done",
        finished_at=datetime.now(timezone.utc).isoformat(),
    )

    # ScoreRecorded(mode=1) vient d'être indexé par The Graph.
    # Déclenche le recalcul EigenTrust pour mettre à jour la matrice C.
    try:
        from app.services.eigentrust_sync import sync_eigentrust_onchain
        import asyncio as _asyncio
        _asyncio.create_task(sync_eigentrust_onchain())
    except Exception as _e:
        logger.warning("EigenTrust sync post-pipeline échoué: %s", _e)


async def _run_one_validation(
    pipeline_task_id: str,
    agent_id:         str,
    val_task_id:      str,
    proxy_cid:        str,
    task_description: str = "",
) -> None:
    """Lance run_validation pour un agent du pipeline (mode=1)."""
    from app.services.judge_service import run_validation
    try:
        await run_validation(
            agent_id, val_task_id, proxy_cid,
            mode=1, task_description=task_description,
        )
    except Exception as exc:
        logger.error(
            "Validation échouée agent=%s pipeline=%s: %s",
            agent_id, pipeline_task_id, exc,
        )

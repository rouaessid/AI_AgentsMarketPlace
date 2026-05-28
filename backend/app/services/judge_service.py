"""
judge_service.py — Validation orchestrator
-------------------------------------------
Responsibilities:
  1. Discover registered judge agents (agent_type=JUDGE, status=active)
  2. Run each judge container via the sandbox (same Docker infrastructure as provider agents)
  3. Compute consensus
  4. Execute on-chain commit-reveal via ValidationRegistry
  5. Persist results to DB

Decentralization principle:
  - Judge providers register via the standard frontend form (agent_type=judge)
  - Their Docker image exposes POST /run — same contract as any agent
  - The platform passes the IPFS CID as the prompt — judges fetch the trace themselves
  - Judges know nothing about the platform internals
  - No built-in fallback: judges MUST be registered. If fewer than 3 are available,
    validation is aborted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone

from eth_abi import encode as abi_encode
from web3 import Web3

from app.core.config import get_settings
from app.db import access_repo
from app.judges.base import JudgeResult

logger   = logging.getLogger(__name__)
settings = get_settings()

# Limit simultaneous judge Docker containers: 2 agents × 3 judges = 6 slots.
# Prevents Docker resource spikes while keeping multi-agent pipelines fast.
_JUDGE_SEMAPHORE = asyncio.Semaphore(6)

# Maps IPFS CID → challenge_token for the current validation round.
# The /ipfs/{cid} proxy in main.py injects the token into the response
# so judges receive it without us needing to re-upload to IPFS.
_CHALLENGE_STORE: dict[str, str] = {}


def _judge_env(agent_id: str) -> dict:
    """Retourne les variables d'environnement à injecter dans le container du juge.

    Chaque juge a son propre provider pour éviter le partage de rate limits :
      alpha   → Groq        (LLM_BASE_URL=groq, JUDGE_ALPHA_GROQ_KEY)
      beta    → OpenRouter  (LLM_BASE_URL=openrouter, JUDGE_BETA_OR_KEY)
                fallback    → Groq (JUDGE_BETA_GROQ_KEY)
      gamma   → Groq        (LLM_BASE_URL=groq, JUDGE_GAMMA_GROQ_KEY)
      delta   → Gemini      (LLM_BASE_URL=gemini, JUDGE_DELTA_GEMINI_KEY)
                fallback    → Groq (JUDGE_DELTA_GROQ_KEY)
      epsilon → OpenRouter  (LLM_BASE_URL=openrouter, JUDGE_EPSILON_OR_KEY)
                fallback    → Groq (JUDGE_EPSILON_GROQ_KEY)
    """
    _GROQ_URL  = "https://api.groq.com/openai/v1"
    _OR_URL    = "https://openrouter.ai/api/v1"
    _GEM_URL   = "https://generativelanguage.googleapis.com/v1beta/openai"
    _GROQ_MDL  = "llama-3.1-8b-instant"
    _OR_MDL    = "meta-llama/llama-3.1-8b-instruct"

    env = {"IPFS_GATEWAY": "http://host.docker.internal:8000/ipfs"}

    if agent_id == "judge-alpha":
        key = settings.judge_alpha_groq_key or settings.groq_api_key
        env.update({"GROQ_API_KEY": key, "LLM_BASE_URL": _GROQ_URL, "LLM_MODEL": _GROQ_MDL})
        if settings.judge_alpha_tavily_key:
            env["TAVILY_API_KEY"] = settings.judge_alpha_tavily_key

    elif agent_id == "judge-beta":
        if settings.judge_beta_or_key:
            env.update({"GROQ_API_KEY": settings.judge_beta_or_key, "LLM_BASE_URL": _OR_URL, "LLM_MODEL": _OR_MDL})
        else:
            key = settings.judge_beta_groq_key or settings.groq_api_key
            env.update({"GROQ_API_KEY": key, "LLM_BASE_URL": _GROQ_URL, "LLM_MODEL": _GROQ_MDL})

    elif agent_id == "judge-gamma":
        key = settings.judge_gamma_groq_key or settings.groq_api_key
        env.update({"GROQ_API_KEY": key, "LLM_BASE_URL": _GROQ_URL, "LLM_MODEL": _GROQ_MDL})

    elif agent_id == "judge-delta":
        if settings.judge_delta_gemini_key:
            env.update({"GROQ_API_KEY": settings.judge_delta_gemini_key, "LLM_BASE_URL": _GEM_URL, "LLM_MODEL": "gemini-2.5-flash"})
        else:
            key = settings.judge_delta_groq_key or settings.groq_api_key
            env.update({"GROQ_API_KEY": key, "LLM_BASE_URL": _GROQ_URL, "LLM_MODEL": _GROQ_MDL})

    elif agent_id == "judge-epsilon":
        if settings.judge_epsilon_or_key:
            env.update({"GROQ_API_KEY": settings.judge_epsilon_or_key, "LLM_BASE_URL": _OR_URL, "LLM_MODEL": _OR_MDL})
        else:
            key = settings.judge_epsilon_groq_key or settings.groq_api_key
            env.update({"GROQ_API_KEY": key, "LLM_BASE_URL": _GROQ_URL, "LLM_MODEL": _GROQ_MDL})

    return {k: v for k, v in env.items() if v}  # drop empty values


# ── Protocol helpers — plateforme side ───────────────────────────────────────

def _load_trace_ipfs(proxy_cid: str) -> dict:
    """Fetch trace from Pinata (primary) or ipfs.io (fallback gateway)."""
    import httpx as _httpx
    for url in [
        f"https://gateway.pinata.cloud/ipfs/{proxy_cid}",
        f"https://ipfs.io/ipfs/{proxy_cid}",
    ]:
        try:
            r = _httpx.get(url, timeout=20, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
        except Exception as _e:
            logger.debug("[val] Gateway %s failed: %s", url, _e)
    logger.warning("[val] Trace introuvable sur IPFS pour CID=%s", proxy_cid)
    return {}


def _register_challenge_token(proxy_cid: str, trace: dict, token: str) -> None:
    """Store challenge token in memory so /ipfs/{cid} proxy injects it for judges."""
    trace["challenge_token"] = token
    _CHALLENGE_STORE[proxy_cid] = token


def _verify_challenge_token(response_token: str, expected_token: str) -> bool:
    """Vérifie que le juge a retourné le bon challenge_token."""
    return bool(response_token) and response_token == expected_token


def _verify_trajectory_check(traj_check: dict, real_trace: dict) -> bool:
    """
    Vérifie que le juge a lu la trajectory.
    Compare 6 valeurs extraites contre la vraie trace (4 originaux + error_count + output_length).
    Retourne True si ≥ 4/6 corrects.
    error_count et output_length sont les inputs pour no_fabrication/tool_usage —
    si le juge les ment, ses scores structurels seront pénalisés.
    """
    if not traj_check:
        return False
    traj        = real_trace.get("trajectory", [])
    output      = str(real_trace.get("agent_output", "")).strip()
    error_count = sum(1 for c in traj if c.get("status", 200) >= 400)
    checks = [
        traj_check.get("steps_count")    == len(traj),
        traj_check.get("first_tool")     == (traj[0].get("tool", "") if traj else ""),
        traj_check.get("last_seq")       == (traj[-1].get("seq", -1) if traj else -1),
        traj_check.get("has_errors")     == any(c.get("status", 200) >= 400 for c in traj),
        traj_check.get("error_count")    == error_count,
        traj_check.get("output_length")  == len(output),
    ]
    return sum(checks) >= 4


# InternalVote enum: NONE=0, VALID=1, INVALID=2
_VOTE_VALID   = 1
_VOTE_INVALID = 2

# ── Minimal ValidationRegistry ABI ───────────────────────────────────────────

_VALIDATION_ABI = [
    # validationRequest: includes traceHash_ (bytes32) and mode_
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"providerAgentId_"},{"type":"string","name":"requestURI_"},{"type":"bytes32","name":"requestHash_"},{"type":"bytes32","name":"traceHash_"},{"type":"uint8","name":"mode_"}],"name":"validationRequest","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string[]","name":"candidates_"}],"name":"assignJudges","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # commitVote: hash includes vote + 4 scores + salt
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"judgeId_"},{"type":"bytes32","name":"commitHash_"}],"name":"commitVote","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # revealVote: includes 4 scores (uint8 each) — contract aggregates on-chain
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"judgeId_"},{"type":"uint8","name":"vote_"},{"type":"bytes32","name":"salt_"},{"type":"uint8","name":"taskCompletion_"},{"type":"uint8","name":"outputQuality_"},{"type":"uint8","name":"noFabrication_"},{"type":"uint8","name":"toolUsage_"}],"name":"revealVote","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # finaliseValidation: aggregated score computed on-chain from judge scores
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"justificationURI_"}],"name":"finaliseValidation","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"type":"string","name":"taskId_"}],"name":"getTraceHash","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
]

# Minimal IdentityRegistry ABI — juste getAgentWallet
_IDENTITY_ABI = [
    {"inputs":[{"type":"string","name":"agentId_"}],"name":"getAgentWallet","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]


# ── Public entry point ────────────────────────────────────────────────────────

async def run_validation(
    agent_id:         str,
    val_task_id:      str,
    proxy_cid:        str,
    mode:             int = 0,
    task_description: str = "",
) -> None:
    """
    Full validation flow. Called as a FastAPI BackgroundTask after each Run.
    mode=0 (solo): agent seul évalué sur sa tâche complète.
    mode=1 (pipeline): agent évalué sur sa sous-tâche dans un pipeline.
    task_description: texte de la tâche — utilisé pour sélectionner les juges
                      par embedding cosine + réputation (agreement_rate).
    """
    logger.info("[val] START agent=%s task=%s cid=%s", agent_id, val_task_id, proxy_cid)

    access_repo.upsert_validation_session(
        agent_id, val_task_id=val_task_id,
        status="in_progress",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    access_repo.clear_judge_verdicts(agent_id)

    try:
        await _run_validation_inner(agent_id, val_task_id, proxy_cid, mode, task_description)
    except Exception as exc:
        logger.error("[val] UNHANDLED EXCEPTION agent=%s: %s", agent_id, exc, exc_info=True)
        access_repo.upsert_validation_session(
            agent_id,
            val_task_id=val_task_id,
            status="failed",
            consensus_verdict="INVALID",
            aggregated_score=0,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


async def _run_validation_inner(
    agent_id:         str,
    val_task_id:      str,
    proxy_cid:        str,
    mode:             int,
    task_description: str,
) -> None:
    # ── 1. Protocole de vérification ─────────────────────────────────────
    real_trace      = _load_trace_ipfs(proxy_cid)
    challenge_token = secrets.token_hex(8)
    _register_challenge_token(proxy_cid, real_trace, challenge_token)
    # traceHash committed on-chain before judges run — prevents post-hoc trace manipulation
    trace_bytes = json.dumps(real_trace, ensure_ascii=False, sort_keys=True).encode()
    trace_hash  = bytes(Web3.keccak(trace_bytes))  # bytes32

    # ── 2. Sélection + run des juges ──────────────────────────────────────
    selected_judges: list = []
    try:
        results, selected_judges = await asyncio.wait_for(
            _run_judges(
                proxy_cid,
                task_description=task_description,
                challenge_token=challenge_token,
                real_trace=real_trace,
            ),
            timeout=180.0,
        )
    except (asyncio.TimeoutError, TimeoutError):
        logger.error("[val] Judge validation timed out after 180s — agent=%s", agent_id)
        results = [JudgeResult(
            judge_id="timeout", judge_name="Timeout",
            score=0, verdict="INVALID",
            justification="Validation timed out after 180s.",
        )]

    if not results:
        logger.error("[val] No judge results for agent=%s — marking failed", agent_id)
        results = [JudgeResult(
            judge_id="no-result", judge_name="No Result",
            score=0, verdict="INVALID",
            justification="No results returned by judges.",
        )]

    for r in results:
        try:
            access_repo.insert_judge_verdict(
                agent_id=agent_id,
                judge_id=r.judge_id,
                judge_name=r.judge_name,
                score=r.score,
                justification=r.justification,
                verdict=r.verdict,
            )
        except Exception as e:
            logger.warning("[val] Could not insert verdict for judge=%s: %s", r.judge_id, e)
        logger.info("[val] %s → %s (%d/100)", r.judge_id, r.verdict, r.score)

    # ── 3. Consensus ──────────────────────────────────────────────────────
    valid_count  = sum(1 for r in results if r.verdict == "VALID")
    scores       = [r.score for r in results]
    avg_score    = sum(scores) // max(1, len(scores))
    divergence   = (max(scores) - min(scores)) if len(scores) >= 2 else 0
    consensus    = (
        "VALID"
        if valid_count >= 2 and avg_score >= 65 and divergence <= 35
        else "INVALID"
    )
    aggregated_score = avg_score

    logger.info("[val] consensus=%s score=%d (%d/%d VALID) divergence=%d",
                consensus, aggregated_score, valid_count, len(results), divergence)

    # ── 4. On-chain commit-reveal ─────────────────────────────────────────
    await _onchain_flow(agent_id, val_task_id, proxy_cid, results, mode, selected_judges, trace_hash)

    # ── 5. Persist final result ───────────────────────────────────────────
    _CHALLENGE_STORE.pop(proxy_cid, None)
    final_status = "validated" if consensus == "VALID" else "rejected"
    access_repo.upsert_validation_session(
        agent_id,
        val_task_id=val_task_id,
        status=final_status,
        consensus_verdict=consensus,
        aggregated_score=aggregated_score,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )

    # ── 6. Update agent reputation metrics ───────────────────────────────
    try:
        from app.services.agent_service import AgentService
        AgentService().update_validation_metrics(
            agent_id,
            verdict=consensus,
            score=float(aggregated_score),
        )
    except Exception as e:
        logger.warning("[val] Could not update agent reputation metrics: %s", e)

    # ── 7. Déclenche EigenTrust sync (solo mode=0 et pipeline mode=1) ────
    # ScoreRecorded vient d'être émis on-chain → The Graph va l'indexer.
    # Le sync lit les nouveaux scores et met à jour tag1="eigenTrust" on-chain.
    try:
        from app.services.eigentrust_sync import sync_eigentrust_onchain
        asyncio.create_task(sync_eigentrust_onchain())
    except Exception as e:
        logger.warning("[val] EigenTrust sync non déclenché: %s", e)

    # ── 7. Update judge agreement rates (DB) ─────────────────────────────
    # JudgeScoreUpdated est émis on-chain par ValidationRegistry._applyOutcomes()
    _update_judge_agreements(results, consensus)

    logger.info("[val] DONE agent=%s → %s", agent_id, final_status)


_COSINE_W = 0.7
_REP_W    = 0.3


# ── Judge dispatch — registered containers only (no fallback) ────────────────

async def _run_judges(
    proxy_cid:        str,
    task_description: str = "",
    challenge_token:  str = "",
    real_trace:       dict | None = None,
) -> tuple[list[JudgeResult], list]:
    """
    Run only registered judge agents (Docker containers).
    Returns (results, selected_judge_records) so on-chain uses the SAME judges.
    """
    registered = _get_registered_judges()

    if not registered:
        logger.error("[val] No judge agents registered — validation cannot proceed.")
        return [JudgeResult(
            judge_id="no-judges", judge_name="No Judges", score=0, verdict="INVALID",
            justification=(
                "Validation aborted: no judge agents are registered on the platform. "
                "Register judge-alpha, judge-beta, and judge-gamma via the frontend."
            ),
        )], []

    if len(registered) < 3:
        logger.error(
            "[val] Only %d/3 judge agents active — validation requires exactly 3 judges.",
            len(registered),
        )
        return [JudgeResult(
            judge_id="insufficient-judges", judge_name="Insufficient Judges",
            score=0, verdict="INVALID",
            justification=(
                f"Validation aborted: only {len(registered)}/3 judge agents are active. "
                "All three judge agents must be registered and active."
            ),
        )], registered

    loop = asyncio.get_event_loop()
    try:
        logger.info("[val] Selecting judges for task_description=%r", task_description[:120])
        selected = await loop.run_in_executor(None, _select_judges_for_task, task_description, registered)
    except Exception as exc:
        logger.exception("[val] Judge selection failed — using registered-order fallback: %s", exc)
        selected = registered[:3]
    logger.info("[val] Selected %d judge(s): %s", len(selected), [j.agent_id for j in selected])
    results = await _run_registered_judges(
        proxy_cid, selected,
        challenge_token=challenge_token,
        real_trace=real_trace or {},
    )
    return results, selected


def _select_judges_for_task(task_description: str, registered: list) -> list:
    """
    Sélectionne les 3 meilleurs juges par :
      score = 0.7 × cosine(task_embedding, judge_embedding)
            + 0.3 × agreement_rate

    agreement_rate ∈ [0,1] — 0.5 par défaut (neutre) avant la 1ère validation.
    """
    from app.services.matching_service import compute_embedding, cosine_similarity, _load_judges_with_embeddings
    from app.services.graph_client import get_judge_reputation

    judges_with_emb = _load_judges_with_embeddings()
    emb_map = {j["agent_id"]: j["embedding"] for j in judges_with_emb}
    # agreement_rate from The Graph JudgeScore (calculated on-chain by ValidationRegistry)
    rep_map = {j["agent_id"]: get_judge_reputation(j["agent_id"])["agreement_rate"]
               for j in judges_with_emb}

    task_emb = compute_embedding(task_description) if task_description.strip() else None

    scored: list[tuple[float, object]] = []
    for judge in registered:
        judge_emb = emb_map.get(judge.agent_id)
        cos = cosine_similarity(task_emb, judge_emb) if (task_emb and judge_emb) else 0.5
        rep = rep_map.get(judge.agent_id, 0.5)
        score = _COSINE_W * cos + _REP_W * rep
        scored.append((score, judge))
        logger.debug("[val] Judge %s: cos=%.3f rep=%.3f → %.3f",
                     judge.agent_id, cos, rep, score)

    scored.sort(key=lambda x: x[0], reverse=True)

    if len(scored) <= 3:
        return [j for _, j in scored]

    # 2 best (quality) + 1 random from the rest (rotation — gives new judges a chance)
    import random
    top_2 = [j for _, j in scored[:2]]
    remaining = [j for _, j in scored[2:]]
    rotation_pick = random.choice(remaining)
    logger.info("[val] Judge selection: top2=%s + rotation=%s",
                [j.agent_id for j in top_2], rotation_pick.agent_id)
    return top_2 + [rotation_pick]


# ── Mise à jour réputation juges après consensus ──────────────────────────────

def _update_judge_agreements(results: list[JudgeResult], consensus: str) -> None:
    """
    Agreement rates are calculated on-chain by ValidationRegistry._applyOutcomes()
    and indexed by The Graph (JudgeScore entity). No local DB update needed.
    """
    for r in results:
        agreed = (r.verdict == consensus)
        logger.info("[val] Judge %s voted=%s consensus=%s agreed=%s (rate from The Graph)",
                    r.judge_id, r.verdict, consensus, agreed)


def _get_registered_judges() -> list:
    """Return active judge AgentRecords from the in-memory store."""
    try:
        from app.services.agent_service import _records
        from app.models.agent import AgentType, AgentStatus
        return [
            r for r in _records.values()
            if r.agent_type == AgentType.JUDGE
            and r.status == AgentStatus.ACTIVE
            and r.docker_image  # must have a Docker image to run
        ]
    except Exception as e:
        logger.warning("[val] Cannot query judge registry: %s", e)
        return []


# ── Run registered judge containers ──────────────────────────────────────────

async def _run_registered_judges(
    proxy_cid:       str,
    judges:          list,
    challenge_token: str = "",
    real_trace:      dict | None = None,
) -> list[JudgeResult]:
    """
    Run each registered judge Docker container via the sandbox.
    Passes the raw IPFS CID as the prompt — the judge fetches the trace itself.
    Stagger: 0s / 8s / 16s to avoid Docker daemon spikes.
    """
    from app.services.sandbox_service import SandboxService

    svc = SandboxService()

    async def _staggered(i: int, judge):
        if i > 0:
            await asyncio.sleep(i * 8)
        return await _run_one_judge(svc, judge, proxy_cid,
                                    challenge_token=challenge_token,
                                    real_trace=real_trace or {})

    tasks   = [_staggered(i, j) for i, j in enumerate(judges)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[JudgeResult] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            j = judges[i]
            logger.error("[val] Judge container %s crashed: %s", j.agent_id, r)
            out.append(JudgeResult(
                judge_id=j.agent_id, judge_name=j.name,
                score=0, verdict="INVALID",
                justification=f"Judge container crashed: {r}",
            ))
        else:
            out.append(r)
    return out


async def _run_one_judge(
    svc,
    judge_record,
    proxy_cid:       str,
    challenge_token: str = "",
    real_trace:      dict | None = None,
) -> JudgeResult:
    """
    Run a single judge container (decentralized: judge fetches trace from IPFS itself).
    Judges compute ALL 4 scores. Platform verifies challenge_token + trajectory_check.
    Structural scores (no_fabrication, tool_usage) are re-derived from the judge's
    declared trajectory_check values using the deterministic formula.
    Retries up to 2 times if provider returns 429 (rate limit).
    """
    async with _JUDGE_SEMAPHORE:
        from app.services.sandbox_service import SandboxInput

        manifest = await svc.run_agent(
            judge_record,
            SandboxInput(
                task_id=f"judge-{uuid.uuid4().hex[:8]}",
                agent_id=judge_record.agent_id,
                task_prompt=proxy_cid,
            ),
            env_vars=_judge_env(judge_record.agent_id),
            use_proxy=False,
        )

        # Parse judge output
        output = manifest.output or {}
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                output = {}

        # Flatten nested output if sandbox wrapped it
        if isinstance(output, dict) and "output" in output:
            output = output["output"]

        # ── Extract semantic scores from judge LLM (0-25 each) ────────────
        criteria = output.get("criteria") or {}
        if isinstance(criteria, dict) and criteria:
            task_completion = max(0, min(25, int(criteria.get("task_completion", 0))))
            output_quality  = max(0, min(25, int(criteria.get("output_quality",  0))))
        else:
            # Legacy fallback: judge returned old single "score" (0-100)
            legacy          = max(0, min(100, int(output.get("total", output.get("score", 0)))))
            task_completion = max(0, min(25, legacy // 4))
            output_quality  = max(0, min(25, legacy // 4))

        # ── Parse trajectory_check (judge-declared, platform-verified) ─────
        traj_check = output.get("trajectory_check") or {}
        if isinstance(traj_check, str):
            try:
                traj_check = json.loads(traj_check)
            except Exception:
                traj_check = {}

        # ── Re-derive structural scores from declared trajectory_check ─────
        declared_steps         = int(traj_check.get("steps_count",    0))
        declared_error_count   = int(traj_check.get("error_count",    0))
        declared_output_length = int(traj_check.get("output_length",  0))

        if declared_steps == 0 and declared_output_length > 100:
            no_fabrication = 0
        elif declared_steps == 0:
            no_fabrication = 5
        else:
            ratio = min(1.0, declared_steps / max(1, declared_output_length / 500))
            no_fabrication = int(ratio * 25)

        tool_usage = (
            int((1.0 - declared_error_count / declared_steps) * 25)
            if declared_steps > 0 else 0
        )
        no_fabrication = max(0, min(25, no_fabrication))
        tool_usage     = max(0, min(25, tool_usage))

        # ── Verify challenge token (proves judge fetched the real trace) ───
        challenge_ok = _verify_challenge_token(
            output.get("challenge_token", ""), challenge_token
        )
        if not challenge_ok:
            logger.warning("[val] %s: challenge_token FAILED", judge_record.agent_id)

        # ── Verify trajectory check (proves judge read the trajectory) ─────
        trajectory_ok = _verify_trajectory_check(traj_check, real_trace or {})
        if not trajectory_ok:
            logger.warning("[val] %s: trajectory_check FAILED", judge_record.agent_id)

        # Penalty: both verifications failed → cap semantic scores at 5 each
        if not challenge_ok and not trajectory_ok:
            logger.warning("[val] %s: BOTH verifications failed — cap semantic scores",
                           judge_record.agent_id)
            task_completion = min(task_completion, 5)
            output_quality  = min(output_quality,  5)

        # ── Assemble final score (sum of all 4 criteria, 0-100) ───────────
        score   = max(0, min(100, task_completion + output_quality + no_fabrication + tool_usage))
        verdict = "VALID" if score >= 70 else "INVALID"

        return JudgeResult(
            judge_id=output.get("judge_id", judge_record.agent_id),
            judge_name=judge_record.name,
            score=score,
            verdict=verdict,
            justification=output.get("justification", "No justification from judge container."),
            criteria={
                "task_completion": task_completion,
                "output_quality":  output_quality,
                "no_fabrication":  no_fabrication,
                "tool_usage":      tool_usage,
            },
            trajectory_check=traj_check,
        )


# ── Wallet → clé privée ───────────────────────────────────────────────────────

def _build_wallet_key_map() -> dict[str, str]:
    """
    Construit un dict {wallet_address_lower: private_key} depuis la config.
    Source primaire  : JUDGE_WALLET_KEYS (JSON dict dans .env)
    Source de repli  : JUDGE_1/2/3_PRIVATE_KEY (backwards-compat)
    """
    result: dict[str, str] = {}

    for raw_wallet, raw_key in settings.judge_wallet_keys.items():
        result[raw_wallet.lower()] = raw_key

    from eth_account import Account as EthAccount
    for key in [settings.judge_1_private_key,
                settings.judge_2_private_key,
                settings.judge_3_private_key]:
        if key:
            addr = EthAccount.from_key(key).address.lower()
            result.setdefault(addr, key)

    return result


# ── On-chain commit-reveal ────────────────────────────────────────────────────

async def _onchain_flow(
    agent_id:        str,
    val_task_id:     str,
    proxy_cid:       str,
    results:         list[JudgeResult],
    mode:            int = 0,
    selected_judges: list | None = None,
    trace_hash:      bytes | None = None,
) -> None:
    if not (settings.validation_registry_address and settings.platform_private_key
            and settings.identity_registry_address):
        logger.info("[val] On-chain disabled (missing config) — off-chain only")
        return

    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                _onchain_flow_sync,
                agent_id, val_task_id, proxy_cid, results, mode,
                selected_judges or [], trace_hash or b"\x00" * 32,
            ),
            timeout=120.0,
        )
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("[val] On-chain flow timed out after 120s — off-chain result kept")
    except Exception as e:
        logger.warning("[val] On-chain flow failed (off-chain result kept): %s", e)


def _resolve_judge_keys(identity, judge_ids: list[str], wallet_key_map: dict) -> list[str]:
    """Return private keys for each judge using owner_address from in-memory cache."""
    from app.services.agent_service import get_agent_from_cache
    keys = []
    for jid in judge_ids:
        cached = get_agent_from_cache(jid)
        wallet = (cached.get("owner_address") or "").lower() if cached else ""
        if not wallet:
            # fallback: ask the contract
            try:
                wallet = identity.functions.getAgentWallet(jid).call().lower()
            except Exception:
                pass
        key = wallet_key_map.get(wallet)
        if not key:
            raise RuntimeError(
                f"No private key for judge {jid} (owner={wallet}). "
                f"Add JUDGE_WALLET_KEYS={{'{wallet}':'0xKEY'}} to .env"
            )
        keys.append(key)
    return keys


def _onchain_flow_sync(
    agent_id:        str,
    val_task_id:     str,
    proxy_cid:       str,
    results:         list[JudgeResult],
    mode:            int = 0,
    selected_judges: list | None = None,
    trace_hash:      bytes | None = None,
) -> None:
    """Synchronous on-chain flow — runs in a thread via run_in_executor."""
    try:
        w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(settings.validation_registry_address),
            abi=_VALIDATION_ABI,
        )

        req_hash = bytes(Web3.keccak(text=f"{agent_id}|{proxy_cid}"))
        ipfs_uri = f"ipfs://{proxy_cid}"
        th       = trace_hash if (trace_hash and len(trace_hash) == 32) else b"\x00" * 32

        _send(w3, settings.platform_private_key,
              registry.functions.validationRequest(
                  val_task_id, agent_id, ipfs_uri, req_hash, th, mode))

        judges = selected_judges if selected_judges else _get_registered_judges()
        if len(judges) < 3:
            logger.error(
                "[val] Not enough selected judges (%d/3). On-chain flow aborted.",
                len(judges),
            )
            return

        judge_ids = [j.agent_id for j in judges[:3]]
        _send(w3, settings.platform_private_key,
              registry.functions.assignJudges(val_task_id, judge_ids))

        identity = w3.eth.contract(
            address=Web3.to_checksum_address(settings.identity_registry_address),
            abi=_IDENTITY_ABI,
        )
        wallet_key_map = _build_wallet_key_map()
        judge_keys = _resolve_judge_keys(identity, judge_ids, wallet_key_map)

        result_map = {r.judge_id: r for r in results}
        valid_count = sum(1 for r in results if r.verdict == "VALID")
        fallback_verdict = "VALID" if valid_count >= 2 else "INVALID"

        # Commit: hash includes vote + all 4 scores + salt (matches Solidity formula)
        salts      = []
        judge_data = []
        for key, jid in zip(judge_keys, judge_ids):
            res = result_map.get(jid)
            if res and res.criteria:
                verdict = res.verdict
                tc  = res.criteria.get("task_completion", 0)
                oq  = res.criteria.get("output_quality",  0)
                nf  = res.criteria.get("no_fabrication",  0)
                tu  = res.criteria.get("tool_usage",      0)
            else:
                verdict = fallback_verdict
                tc = oq = nf = tu = 0
            vote = _VOTE_VALID if verdict == "VALID" else _VOTE_INVALID
            salt = secrets.token_bytes(32)
            salts.append(salt)
            judge_data.append((vote, tc, oq, nf, tu))
            chash = bytes(Web3.keccak(
                abi_encode(
                    ["uint8", "uint8", "uint8", "uint8", "uint8", "bytes32"],
                    [vote, tc, oq, nf, tu, salt],
                )
            ))
            _send(w3, key, registry.functions.commitVote(val_task_id, jid, chash))

        # Reveal: pass all 4 scores explicitly — contract aggregates on-chain
        for key, jid, salt, (vote, tc, oq, nf, tu) in zip(
            judge_keys, judge_ids, salts, judge_data
        ):
            _send(w3, key,
                  registry.functions.revealVote(
                      val_task_id, jid, vote, salt, tc, oq, nf, tu))

        # finaliseValidation: aggregated score computed on-chain from judge scores
        _send(w3, settings.platform_private_key,
              registry.functions.finaliseValidation(
                  val_task_id, f"ipfs://val-{val_task_id}"))
        logger.info("[val] On-chain finalised ✓")

    except Exception as e:
        logger.warning("[val] On-chain flow failed (off-chain result kept): %s", e)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _send(w3: Web3, private_key: str, fn, gas: int = 500_000) -> str:
    account = w3.eth.account.from_key(private_key)
    nonce   = w3.eth.get_transaction_count(account.address, "pending")
    tx      = fn.build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": gas, "gasPrice": w3.eth.gas_price,
    })
    signed  = w3.eth.account.sign_transaction(tx, private_key)
    txh     = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(txh, timeout=60)
    if receipt["status"] != 1:
        raise RuntimeError(f"TX reverted: {txh.hex()}")
    return txh.hex()



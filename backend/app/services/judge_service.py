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
import time
import uuid
from datetime import datetime, timezone

from eth_abi import encode as abi_encode
from web3 import Web3

from app.core.config import get_settings
from app.repo import access_repo
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
_SCORE_FROM_RECEIPT: dict[str, int] = {}   # val_task_id → aggregatedScore parsé du receipt
_PIPELINE_SCORES:   dict[str, float] = {}  # agent_id → score, accumulé en mode=1

# Serialise concurrent on-chain setups to avoid nonce collisions when multiple
# pipeline agents submit validationRequest TXs at the same time.
_ONCHAIN_SETUP_LOCK: asyncio.Lock | None = None

def _get_onchain_lock() -> asyncio.Lock:
    global _ONCHAIN_SETUP_LOCK
    if _ONCHAIN_SETUP_LOCK is None:
        _ONCHAIN_SETUP_LOCK = asyncio.Lock()
    return _ONCHAIN_SETUP_LOCK


def _judge_env(agent_id: str) -> dict:
    """Retourne les variables d'environnement à injecter dans le container du juge.

    Distribution providers (clés séparées, pas de quota partagé) :
      alpha   → Groq    (JUDGE_ALPHA_GROQ_KEY)
      beta    → Groq    (JUDGE_BETA_GROQ_KEY)
      gamma   → Mistral (JUDGE_GAMMA_MISTRAL_KEY)
      delta   → Mistral (JUDGE_DELTA_MISTRAL_KEY)
      epsilon → Groq    (JUDGE_EPSILON_GROQ_KEY)
    """
    env = {"IPFS_GATEWAY": "http://host.docker.internal:8000/ipfs"}

    if agent_id == "judge-alpha":
        key = settings.judge_alpha_groq_key or settings.groq_api_key
        if key:
            env["GROQ_API_KEY"] = key
        if settings.judge_alpha_tavily_key:
            env["TAVILY_API_KEY"] = settings.judge_alpha_tavily_key
        return env

    if agent_id == "judge-beta":
        key = settings.judge_beta_groq_key or settings.groq_api_key
        if key:
            env["GROQ_API_KEY"] = key
        return env

    if agent_id == "judge-gamma":
        key = settings.judge_gamma_mistral_key
        if key:
            env["GROQ_API_KEY"] = key
        return env

    if agent_id == "judge-delta":
        key = settings.judge_delta_mistral_key
        if key:
            env["GROQ_API_KEY"] = key
        return env

    if agent_id == "judge-epsilon":
        key = settings.judge_epsilon_groq_key or settings.groq_api_key
        if key:
            env["GROQ_API_KEY"] = key
        return env

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

from app.core.abis import VALIDATION_REGISTRY_ABI as _VALIDATION_ABI
from app.core.abis import IDENTITY_REGISTRY_ABI   as _IDENTITY_ABI


# ── IPFS justification upload ────────────────────────────────────────────────

async def _build_and_upload_justifications(
    val_task_id:      str,
    results:          list[JudgeResult],
    consensus:        str,
    aggregated_score: int,
) -> str:
    """
    Construit un document JSON agrégé de tous les verdicts juges et l'upload sur IPFS.
    Le CID est ancré on-chain via finaliseValidation(justificationURI_).
    Retourne l'URI IPFS ou un fallback si l'upload échoue.
    """
    import json as _json
    from app.services.ipfs_service import IPFSService
    doc = _json.dumps({
        "task_id":          val_task_id,
        "consensus":        consensus,
        "aggregated_score": aggregated_score,
        "judges": [
            {
                "judge_id":      r.judge_id,
                "judge_name":    r.judge_name,
                "score":         r.score,
                "verdict":       r.verdict,
                "justification": r.justification,
            }
            for r in results
        ],
    })
    try:
        cid, _, _ = await IPFSService().upload(doc, name=f"verdicts-{val_task_id}")
        logger.info("[val] Justifications uploaded to IPFS: %s", cid)
        return f"ipfs://{cid}"
    except Exception as e:
        logger.warning("[val] Justification IPFS upload failed: %s", e)
        return f"ipfs://val-{val_task_id}"  # fallback non-résolvable mais non-bloquant


# ── Public entry point ────────────────────────────────────────────────────────

async def run_validation(
    agent_id:         str,
    val_task_id:      str,
    proxy_cid:        str,
    mode:             int = 0,
    task_description: str = "",
) -> bool:
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
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        await _run_validation_inner(agent_id, val_task_id, proxy_cid, mode, task_description)
    except Exception as exc:
        logger.error("[val] UNHANDLED EXCEPTION agent=%s: %s", agent_id, exc, exc_info=True)
        access_repo.upsert_validation_session(agent_id, val_task_id=val_task_id)


async def _run_validation_inner(
    agent_id:         str,
    val_task_id:      str,
    proxy_cid:        str,
    mode:             int,
    task_description: str,
) -> None:
    loop = asyncio.get_event_loop()

    # ── 1. Protocol setup ────────────────────────────────────────────────
    real_trace      = _load_trace_ipfs(proxy_cid)
    challenge_token = secrets.token_hex(8)
    _register_challenge_token(proxy_cid, real_trace, challenge_token)
    trace_bytes = json.dumps(real_trace, ensure_ascii=False, sort_keys=True).encode()
    trace_hash  = bytes(Web3.keccak(trace_bytes))

    # ── 2. Select judge candidates (cosine + rep, no run yet) ────────────
    registered = _get_registered_judges()
    try:
        candidates = await loop.run_in_executor(
            None, _select_judge_candidates, task_description, registered
        )
    except Exception as exc:
        logger.warning("[val] Candidate selection failed — using all registered: %s", exc)
        candidates = registered

    if len(candidates) < 3:
        logger.error("[val] Not enough judge candidates (%d/3) — aborting", len(candidates))
        access_repo.upsert_validation_session(agent_id, val_task_id="FAILED")
        return

    # ── 3. On-chain: validationRequest + assignJudges ────────────────────
    onchain_enabled = bool(
        settings.validation_registry_address and
        settings.platform_private_key and
        settings.identity_registry_address
    )
    assigned_token_ids: list[int] = []
    assigned_agent_ids: list[str] = []
    judge_keys:         list[str] = []

    if onchain_enabled:
        _max_setup_attempts = 4
        _retry_delay_s      = 45
        _last_setup_exc: Exception | None = None
        for _attempt in range(_max_setup_attempts):
            try:
                async with _get_onchain_lock():
                    assigned_token_ids, judge_keys, assigned_agent_ids = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, _onchain_setup_sync,
                            agent_id, val_task_id, proxy_cid, mode, trace_hash,
                            [j.agent_id for j in candidates],
                        ),
                        timeout=120.0,
                    )
                logger.info("[val] On-chain assigned tokenIds=%s agentIds=%s",
                            assigned_token_ids, assigned_agent_ids)
                _last_setup_exc = None
                break
            except Exception as _e:
                _last_setup_exc = _e
                if _attempt < _max_setup_attempts - 1:
                    logger.warning(
                        "[val] On-chain setup attempt %d/%d failed — retrying in %ds: %s",
                        _attempt + 1, _max_setup_attempts, _retry_delay_s, _e,
                    )
                    await asyncio.sleep(_retry_delay_s)
        if _last_setup_exc is not None:
            logger.error("[val] On-chain setup failed after %d attempts: %s",
                         _max_setup_attempts, _last_setup_exc)
            access_repo.upsert_validation_session(agent_id, val_task_id="FAILED")
            return
    else:
        logger.info("[val] On-chain disabled — using first 3 candidates")
        assigned_agent_ids = [j.agent_id for j in candidates[:3]]

    # ── 4. Run the on-chain assigned judges ──────────────────────────────
    id_set          = set(assigned_agent_ids)
    assigned_records = sorted(
        [j for j in registered if j.agent_id in id_set],
        key=lambda j: assigned_agent_ids.index(j.agent_id),
    )
    if len(assigned_records) < 3:
        logger.error("[val] Assigned judges not all registered locally (%d/3) — aborting",
                     len(assigned_records))
        access_repo.upsert_validation_session(agent_id, val_task_id="FAILED")
        return

    try:
        results = await asyncio.wait_for(
            _run_registered_judges(
                proxy_cid, assigned_records,
                challenge_token=challenge_token,
                real_trace=real_trace,
            ),
            timeout=180.0,
        )
    except (asyncio.TimeoutError, TimeoutError):
        logger.error("[val] Judge execution timed out after 180s — agent=%s", agent_id)
        results = [JudgeResult(
            judge_id="timeout", judge_name="Timeout",
            score=0, verdict="INVALID",
            justification="Validation timed out after 180s.",
        )]

    if not results:
        results = [JudgeResult(
            judge_id="no-result", judge_name="No Result",
            score=0, verdict="INVALID",
            justification="No results returned by judges.",
        )]

    for r in results:
        logger.info("[val] %s → %s (%d/100)", r.judge_id, r.verdict, r.score)

    # ── 5. Consensus ─────────────────────────────────────────────────────
    valid_count      = sum(1 for r in results if r.verdict == "VALID")
    scores           = [r.score for r in results]
    avg_score        = sum(scores) // max(1, len(scores))
    divergence       = (max(scores) - min(scores)) if len(scores) >= 2 else 0
    consensus        = (
        "VALID"
        if valid_count >= 2 and avg_score >= 65 and divergence <= 35
        else "INVALID"
    )
    aggregated_score = avg_score
    logger.info("[val] consensus=%s score=%d (%d/%d VALID) divergence=%d",
                consensus, aggregated_score, valid_count, len(results), divergence)

    # ── 6. Upload justifications to IPFS ─────────────────────────────────
    justification_uri = await _build_and_upload_justifications(
        val_task_id, results, consensus, aggregated_score
    )

    # ── 7. On-chain: commits + reveals + finalise ─────────────────────────
    onchain_ok = False
    if onchain_enabled and judge_keys:
        try:
            onchain_ok = await asyncio.wait_for(
                loop.run_in_executor(
                    None, _onchain_conclude_sync,
                    val_task_id, results, assigned_token_ids, assigned_agent_ids, judge_keys, justification_uri,
                ),
                timeout=120.0,
            )
        except Exception as e:
            logger.warning("[val] On-chain conclude failed: %s", e)

    # ── 8. Read authoritative verdict + persist ───────────────────────────
    onchain_verdict = _read_onchain_verdict(val_task_id) if onchain_ok else None
    onchain_verdict = onchain_verdict or consensus

    _CHALLENGE_STORE.pop(proxy_cid, None)
    access_repo.upsert_validation_session(
        agent_id, val_task_id=val_task_id if onchain_ok else "FAILED"
    )

    # ── 9. Agent reputation metrics ───────────────────────────────────────
    try:
        from app.services.agent_service import AgentService
        AgentService().update_validation_metrics(agent_id, score=float(aggregated_score))
    except Exception as e:
        logger.warning("[val] Could not update agent reputation metrics: %s", e)

    # ── 10. EigenTrust — score from finaliseValidation receipt ───────────
    try:
        fresh_score = float(_SCORE_FROM_RECEIPT.pop(val_task_id, 0) or 0)
        if mode == 0:
            # Solo: déclenché immédiatement par agent
            from app.services.eigentrust_sync import compute_and_write_eigentrust
            asyncio.create_task(compute_and_write_eigentrust(agent_id, fresh_score))
        elif fresh_score > 0:
            # Pipeline: accumulate — execution_service déclenchera une fois pour tous
            _PIPELINE_SCORES[agent_id] = fresh_score
    except Exception as e:
        logger.warning("[val] EigenTrust non déclenché: %s", e)

    # ── 11. Judge agreement rates ─────────────────────────────────────────
    _update_judge_agreements(results, consensus)

    logger.info("[val] DONE agent=%s → %s", agent_id, onchain_verdict)


_COSINE_W = 0.7
_REP_W    = 0.3


def _select_judge_candidates(task_description: str, registered: list, n: int = 5) -> list:
    """
    Select top N judge candidates by cosine similarity + reputation.
    These are passed as candidates to assignJudges — the contract picks 3 via Fisher-Yates.
    Returns all registered if fewer than N are available.
    """
    if len(registered) <= n:
        return registered

    from app.services.matching_service import compute_embedding, cosine_similarity, _load_judges_with_embeddings
    from app.services.graph_client import get_judge_agreement_rate

    judges_with_emb = _load_judges_with_embeddings()
    emb_map = {j["agent_id"]: j["embedding"] for j in judges_with_emb}
    rep_map = {j["agent_id"]: get_judge_agreement_rate(j["agent_id"])["agreement_rate"]
               for j in judges_with_emb}

    task_emb = compute_embedding(task_description) if task_description.strip() else None

    scored: list[tuple[float, object]] = []
    for judge in registered:
        judge_emb = emb_map.get(judge.agent_id)
        cos = cosine_similarity(task_emb, judge_emb) if (task_emb and judge_emb) else 0.5
        rep = rep_map.get(judge.agent_id, 0.5)
        score = _COSINE_W * cos + _REP_W * rep
        scored.append((score, judge))
        logger.debug("[val] Judge %s: cos=%.3f rep=%.3f → %.3f", judge.agent_id, cos, rep, score)

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [j for _, j in scored[:n]]
    logger.info("[val] Candidates selected (%d): %s", len(candidates), [j.agent_id for j in candidates])
    return candidates


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


# ── Lecture verdict autoritatif depuis le contrat ────────────────────────────

def _read_onchain_verdict(val_task_id: str) -> str | None:
    """
    Lit ValidationTask.finalTag directement via RPC après finaliseValidation().
    Variable d'état — disponible immédiatement sans attendre The Graph.
    Retourne "VALID", "INVALID", "DISPUTED" ou None si indisponible.
    """
    if not settings.validation_registry_address:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 5}))
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(settings.validation_registry_address),
            abi=_VALIDATION_ABI,
        )
        task = registry.functions.getTask(val_task_id).call()
        # ValidationTask tuple index 12 : taskId(0) providerTokenId(1) providerWallet(2)
        # requestHash(3) traceHash(4) status(5) createdAt(6) commitDeadline(7)
        # revealDeadline(8) judgeTokenIds(9) judgeWallets(10) finalResponse(11) finalTag(12)
        # score(13) mode(14)
        final_tag = task[12] if isinstance(task, (list, tuple)) else getattr(task, "finalTag", None)
        return final_tag if final_tag in ("VALID", "INVALID", "DISPUTED") else None
    except Exception as e:
        # 0x3e0100ea = TaskNotFound(string) — expected before validationRequest is mined
        if "0x3e0100ea" not in str(e):
            logger.debug("[val] Could not read on-chain verdict for %s: %s", val_task_id, e)
        return None


# ── On-chain phase 1 : validationRequest + assignJudges ──────────────────────

def _onchain_setup_sync(
    agent_id:           str,
    val_task_id:        str,
    proxy_cid:          str,
    mode:               int,
    trace_hash:         bytes,
    candidate_agent_ids: list[str],
) -> tuple[list[int], list[str], list[str]]:
    """
    Submit validationRequest + assignJudges on-chain.
    Resolves agentId strings → tokenIds before all contract calls.
    Returns (assigned_token_ids, judge_private_keys, assigned_agent_ids).
    """
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
    registry = w3.eth.contract(
        address=Web3.to_checksum_address(settings.validation_registry_address),
        abi=_VALIDATION_ABI,
    )
    identity = w3.eth.contract(
        address=Web3.to_checksum_address(settings.identity_registry_address),
        abi=_IDENTITY_ABI,
    )

    # Resolve provider agentId → tokenId
    provider_token_id = identity.functions.getCurrentTokenId(agent_id).call()
    logger.info("[val] Resolved provider %s → tokenId=%d", agent_id, provider_token_id)

    # Resolve candidate agentIds → tokenIds
    candidate_token_ids: list[int] = []
    for cid in candidate_agent_ids:
        try:
            tid = identity.functions.getCurrentTokenId(cid).call()
            candidate_token_ids.append(tid)
        except Exception as _e:
            logger.warning("[val] Could not resolve candidate %s to tokenId: %s", cid, _e)
    if len(candidate_token_ids) < 3:
        raise RuntimeError(
            f"Not enough resolvable candidate tokenIds ({len(candidate_token_ids)}/3)"
        )

    req_hash = bytes(Web3.keccak(text=f"{agent_id}|{proxy_cid}"))
    ipfs_uri = f"ipfs://{proxy_cid}"
    th       = trace_hash if (trace_hash and len(trace_hash) == 32) else b"\x00" * 32

    logger.info("[val] Using contract=%s  task=%s", registry.address, val_task_id)

    # Crash recovery: check if task already exists
    _preexisting = None
    try:
        _preexisting = registry.functions.getTask(val_task_id).call()
    except Exception:
        pass

    if _preexisting is not None:
        status = _preexisting[5]
        if status in (1, 2):
            logger.warning("[val] Task %s stuck (status=%d) — expiring", val_task_id, status)
            try:
                _send(w3, settings.platform_private_key,
                      registry.functions.expireTask(val_task_id), gas=500_000)
                logger.info("[val] expireTask OK")
            except Exception as _ee:
                logger.warning("[val] expireTask failed: %s", _ee)
            raise RuntimeError(f"Task {val_task_id} was stuck (status={status}), now expired.")
        elif status >= 3:
            raise RuntimeError(f"Task {val_task_id} already finalised/expired (status={status})")
        # status == 0 (PENDING): validationRequest already done, skip to assignJudges

    if _preexisting is None:
        txh_vr, _ = _send(w3, settings.platform_private_key,
                          registry.functions.validationRequest(
                              val_task_id, provider_token_id, ipfs_uri, req_hash, th, mode))
        logger.info("[val] validationRequest TX=%s", txh_vr)
        for _attempt in range(3):
            try:
                registry.functions.getTask(val_task_id).call()
                break
            except Exception as _e:
                if _attempt == 2:
                    raise RuntimeError(f"Task {val_task_id} not found after TX: {_e}") from _e
                logger.warning("[val] getTask attempt %d/3 — retrying in 3s", _attempt + 1)
                time.sleep(3)

    txh_aj, aj_receipt = _send(w3, settings.platform_private_key,
                               registry.functions.assignJudges(val_task_id, candidate_token_ids),
                               gas=600_000)
    logger.info("[val] assignJudges TX=%s", txh_aj)

    try:
        _ev             = registry.events.JudgesAssigned().process_receipt(aj_receipt)[0]["args"]
        judge_token_ids = [int(_ev["judge0"]), int(_ev["judge1"]), int(_ev["judge2"])]
        logger.info("[val] On-chain assigned tokenIds: %s  commit=%d reveal=%d",
                    judge_token_ids, _ev["commitDeadline"], _ev["revealDeadline"])
    except Exception as _ep:
        logger.warning("[val] JudgesAssigned event parse failed — fallback getTask: %s", _ep)
        task_state      = registry.functions.getTask(val_task_id).call()
        judge_token_ids = [int(t) for t in task_state[9]]
        logger.info("[val] On-chain assigned tokenIds (getTask): %s", judge_token_ids)

    # Reverse-resolve tokenIds → agentIds
    assigned_agent_ids: list[str] = []
    for tid in judge_token_ids:
        try:
            aid = identity.functions.getAgentIdByToken(tid).call()
            assigned_agent_ids.append(aid)
        except Exception as _e:
            logger.warning("[val] Could not reverse-resolve tokenId=%d: %s", tid, _e)
            assigned_agent_ids.append(str(tid))

    judge_keys = _resolve_judge_keys(identity, judge_token_ids, _build_wallet_key_map())
    return judge_token_ids, judge_keys, assigned_agent_ids


def _resolve_judge_keys(identity, judge_token_ids: list[int], wallet_key_map: dict) -> list[str]:
    """Return private keys for each judge, using tokenId for on-chain wallet lookup."""
    from app.services.agent_service import get_agent_from_cache
    keys = []
    for tid in judge_token_ids:
        wallet = ""
        # Try cache first: resolve tokenId → agentId, then look up cached wallet
        try:
            aid    = identity.functions.getAgentIdByToken(tid).call()
            cached = get_agent_from_cache(aid)
            wallet = (cached.get("owner_address") or "").lower() if cached else ""
        except Exception:
            pass
        # Fallback: direct on-chain wallet lookup by tokenId
        if not wallet:
            try:
                wallet = identity.functions.getAgentWalletByTokenId(tid).call().lower()
            except Exception:
                pass
        key = wallet_key_map.get(wallet)
        if not key:
            raise RuntimeError(
                f"No private key for judge tokenId={tid} (wallet={wallet}). "
                f"Add JUDGE_WALLET_KEYS={{'{wallet}':'0xKEY'}} to .env"
            )
        keys.append(key)
    return keys


# ── On-chain phase 2 : commitVote + revealVote + finaliseValidation ───────────

def _onchain_conclude_sync(
    val_task_id:       str,
    results:           list[JudgeResult],
    judge_token_ids:   list[int],
    judge_agent_ids:   list[str],
    judge_keys:        list[str],
    justification_uri: str,
) -> bool:
    """
    Submit commits, reveals, then finaliseValidation.
    judge_token_ids: on-chain uint256 tokenIds (for contract calls).
    judge_agent_ids: string agentIds (for matching JudgeResult objects).
    Returns True on success.
    """
    try:
        w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(settings.validation_registry_address),
            abi=_VALIDATION_ABI,
        )

        result_map = {r.judge_id: r for r in results}

        # Build commit hashes (indexed by agentId for result lookup)
        salts: list[bytes] = []
        judge_data: list[tuple] = []
        commit_hashes: list[bytes] = []
        for agent_id in judge_agent_ids:
            res = result_map.get(agent_id)
            if res and res.criteria:
                vote = _VOTE_VALID if res.verdict == "VALID" else _VOTE_INVALID
                tc = res.criteria.get("task_completion", 0)
                oq = res.criteria.get("output_quality",  0)
                nf = res.criteria.get("no_fabrication",  0)
                tu = res.criteria.get("tool_usage",      0)
            else:
                logger.warning("[val] Judge %s has no result (shouldn't happen)", agent_id)
                vote = _VOTE_INVALID
                tc = oq = nf = tu = 0
            salt = secrets.token_bytes(32)
            salts.append(salt)
            judge_data.append((vote, tc, oq, nf, tu))
            commit_hashes.append(bytes(Web3.keccak(
                abi_encode(["uint8", "uint8", "uint8", "uint8", "uint8", "bytes32"],
                           [vote, tc, oq, nf, tu, salt])
            )))

        # Fire-and-forget commits (use tokenIds for contract calls)
        _wallet_nonce: dict[str, int] = {}
        _commit_pending: list[tuple] = []
        for key, tid, agent_id, chash in zip(judge_keys, judge_token_ids, judge_agent_ids, commit_hashes):
            _acct = w3.eth.account.from_key(key)
            _addr = _acct.address
            if _addr not in _wallet_nonce:
                _wallet_nonce[_addr] = w3.eth.get_transaction_count(_addr, "pending")
            _nonce = _wallet_nonce[_addr]; _wallet_nonce[_addr] += 1
            _fn  = registry.functions.commitVote(val_task_id, tid, chash)
            _tx  = _fn.build_transaction({"from": _addr, "nonce": _nonce,
                                           "gas": 1_200_000, "gasPrice": w3.eth.gas_price})
            _sig = w3.eth.account.sign_transaction(_tx, key)
            _txh = w3.eth.send_raw_transaction(_sig.raw_transaction)
            _commit_pending.append((_txh, _tx))
            logger.info("[val] commitVote submitted: tokenId=%d agent=%s nonce=%d txh=%s",
                        tid, agent_id, _nonce, _txh.hex())

        for _txh, _tx in _commit_pending:
            _rcpt = w3.eth.wait_for_transaction_receipt(_txh, timeout=120)
            if _rcpt["status"] != 1:
                try:
                    w3.eth.call({"to": _rcpt["to"], "data": _tx["data"],
                                 "from": _tx["from"], "gas": _tx["gas"]}, _rcpt["blockNumber"])
                except Exception as _ce:
                    raise RuntimeError(f"commitVote reverted ({_txh.hex()}): {_ce}") from _ce
                raise RuntimeError(f"commitVote reverted (no reason): {_txh.hex()}")
        logger.info("[val] All commits confirmed")

        # Fire-and-forget reveals (use tokenIds for contract calls)
        _wallet_nonce = {}
        _reveal_pending: list[tuple] = []
        for key, tid, salt, (vote, tc, oq, nf, tu) in zip(judge_keys, judge_token_ids, salts, judge_data):
            _acct = w3.eth.account.from_key(key)
            _addr = _acct.address
            if _addr not in _wallet_nonce:
                _wallet_nonce[_addr] = w3.eth.get_transaction_count(_addr, "pending")
            _nonce = _wallet_nonce[_addr]; _wallet_nonce[_addr] += 1
            _fn  = registry.functions.revealVote(val_task_id, tid, vote, salt, tc, oq, nf, tu)
            _tx  = _fn.build_transaction({"from": _addr, "nonce": _nonce,
                                           "gas": 1_200_000, "gasPrice": w3.eth.gas_price})
            _sig = w3.eth.account.sign_transaction(_tx, key)
            _txh = w3.eth.send_raw_transaction(_sig.raw_transaction)
            _reveal_pending.append((_txh, _tx))
            logger.info("[val] revealVote submitted: tokenId=%d nonce=%d txh=%s", tid, _nonce, _txh.hex())

        for _txh, _tx in _reveal_pending:
            _rcpt = w3.eth.wait_for_transaction_receipt(_txh, timeout=120)
            if _rcpt["status"] != 1:
                try:
                    w3.eth.call({"to": _rcpt["to"], "data": _tx["data"],
                                 "from": _tx["from"], "gas": _tx["gas"]}, _rcpt["blockNumber"])
                except Exception as _ce:
                    raise RuntimeError(f"revealVote reverted ({_txh.hex()}): {_ce}") from _ce
                raise RuntimeError(f"revealVote reverted (no reason): {_txh.hex()}")
        logger.info("[val] All reveals confirmed")

        _, finalise_receipt = _send(w3, settings.platform_private_key,
                                    registry.functions.finaliseValidation(
                                        val_task_id,
                                        justification_uri or f"ipfs://val-{val_task_id}"))
        logger.info("[val] On-chain finalised ✓")

        try:
            score_events = registry.events.ScoreRecorded().process_receipt(finalise_receipt)
            if score_events:
                _SCORE_FROM_RECEIPT[val_task_id] = int(score_events[0]["args"]["score"])
                logger.info("[val] ScoreRecorded parsé: score=%d", _SCORE_FROM_RECEIPT[val_task_id])
        except Exception as _pe:
            logger.warning("[val] ScoreRecorded parse échoué: %s", _pe)

        return True

    except Exception as e:
        logger.exception("[val] On-chain conclude failed: %s", e)
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _send(w3: Web3, private_key: str, fn, gas: int = 1_200_000):
    """Returns (txHash, receipt)."""
    account = w3.eth.account.from_key(private_key)
    nonce   = w3.eth.get_transaction_count(account.address, "pending")
    tx      = fn.build_transaction({
        "from": account.address, "nonce": nonce,
        "gas": gas, "gasPrice": w3.eth.gas_price,
    })
    signed  = w3.eth.account.sign_transaction(tx, private_key)
    txh     = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(txh, timeout=120)
    if receipt["status"] != 1:
        _call_params = {"to": receipt["to"], "data": tx["data"],
                        "from": account.address, "gas": gas}
        # Replay at the exact revert block; fall back to "latest" if the RPC node
        # doesn't have that block (common on Base Sepolia public nodes).
        for _block_ref in [receipt["blockNumber"], "latest"]:
            try:
                w3.eth.call(_call_params, _block_ref)
            except Exception as _ce:
                if "block not found" in str(_ce).lower() and _block_ref == receipt["blockNumber"]:
                    continue  # retry at "latest"
                raise RuntimeError(f"TX reverted ({txh.hex()}): {_ce}") from _ce
        raise RuntimeError(f"TX reverted (no reason): {txh.hex()}")
    return txh.hex(), receipt



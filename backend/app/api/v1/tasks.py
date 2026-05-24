"""
tasks.py — Task Orchestration API

POST /tasks/plan-only           — Planner + matching, returns plan preview (no execution)
POST /tasks/alternatives        — Ranked alternative agents for a subtask
POST /tasks/pipeline-purchase-info — Parameters for depositPaymentPipeline MetaMask tx
POST /tasks/execute             — Start execution of a plan-ready task
POST /tasks/run                 — Full pipeline: plan + match + execute in background
GET  /tasks/{task_id}/status    — Poll task status
GET  /tasks/                    — List recent tasks
"""
from __future__ import annotations

import json as _json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.pipeline_repo import (
    create_pipeline_task,
    get_pipeline_task,
    list_pipeline_tasks,
    update_pipeline_task,
)
from app.services.matching_service import select_agents, COSINE_WEIGHT, EIGENTRUST_WEIGHT
from app.services.planner_service import decompose_task, decompose_task_alternatives

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])

_SENSITIVE_ENV_KEY_PARTS = (
    "PRIVATE_KEY",
    "SECRET_KEY",
    "WALLET_KEY",
    "MNEMONIC",
    "SEED_PHRASE",
)


def _public_env_var_keys(keys: list | None) -> list[str]:
    """Return only buyer-enterable runtime keys, never wallet/private-key secrets."""
    return [
        str(key)
        for key in (keys or [])
        if not any(part in str(key).upper() for part in _SENSITIVE_ENV_KEY_PARTS)
    ]


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _run_planner_and_matching(prompt: str):
    """Returns (plan, matches, trust_scores). Raises HTTPException on failure."""
    try:
        plan = await decompose_task(prompt)
    except Exception as exc:
        logger.error("Planner failed: %s", exc)
        raise HTTPException(503, detail=f"Planner indisponible : {exc}")

    try:
        from app.services.eigentrust_service import compute_eigentrust
        from app.db.identity_repo import get_all_agent_identities
        from app.db.collaboration_repo import get_solo_scores, get_pipeline_scores

        all_ids = get_all_agent_identities()
        agents  = [
            {"agent_id": r["agent_id"], "token_id": r["current_token_id"]}
            for r in all_ids
            if r.get("current_token_id") and r.get("agent_type", 0) != 1
        ]
        p_overrides = {}
        for a in agents:
            scores = get_solo_scores(a["agent_id"]) or get_pipeline_scores(a["agent_id"])
            if scores:
                nonzero = [s for s in scores if s > 0]
                recent  = nonzero[-5:] if nonzero else []
                if recent:
                    p_overrides[a["agent_id"]] = sum(recent) / len(recent)

        et_result    = compute_eigentrust(agents, task_p_overrides=p_overrides or None)
        trust_scores = {
            aid: et_result.scores_by_agent[aid]["global_trust"]
            for aid in et_result.scores_by_agent
        }
        matches = select_agents(plan.subtasks, trust_scores)
    except Exception as exc:
        logger.error("Matching failed: %s", exc)
        raise HTTPException(503, detail=f"Matching indisponible : {exc}")

    if not matches:
        raise HTTPException(503, detail="Aucun agent disponible pour cette tâche")

    return plan, matches, trust_scores


def _enrich_matches(matches: list) -> list[dict]:
    """Enrich each AgentMatch with agent metadata (name, price, wallet, description)."""
    from app.db.identity_repo import get_agent_identity
    enriched = []
    for m in matches:
        identity = get_agent_identity(m.agent_id) or {}
        meta_raw = identity.get("identity_metadata") or "{}"
        meta = _json.loads(meta_raw) if isinstance(meta_raw, str) else {}
        price = float(identity.get("price_per_task") or 0.0)
        
        caps = meta.get("capabilities", {})
        sand = meta.get("sandbox_config", {})
        env_var_keys = _public_env_var_keys(
            caps.get("env_var_keys")
            or sand.get("env_var_keys")
            or meta.get("env_var_keys")
            or []
        )

        enriched.append({
            "subtask_id":         m.subtask_id,
            "agent_id":           m.agent_id,
            "agent_name":         identity.get("name") or meta.get("name") or m.agent_id,
            "description":        meta.get("description") or "",
            "cosine_score":       m.cosine_score,
            "trust_score":        m.trust_score,
            "final_score":        m.final_score,
            "price_per_task":     price,
            "price_per_task_wei": int(price * 1e18),
            "wallet":             identity.get("owner_address") or "",
            "env_var_keys":       env_var_keys,
        })
    return enriched


def _encode_deposit_pipeline_call(task_id: str, agent_ids: list, wallets: list, shares_bps: list) -> str:
    """ABI-encode depositPaymentPipeline(string,string[],address[],uint256[]) call data."""
    try:
        from web3 import Web3
        from eth_abi import encode as abi_encode

        sig      = "depositPaymentPipeline(string,string[],address[],uint256[])"
        selector = Web3.keccak(text=sig)[:4]

        checksum_wallets = [Web3.to_checksum_address(w) if w else "0x" + "0" * 40 for w in wallets]
        encoded = abi_encode(
            ["string", "string[]", "address[]", "uint256[]"],
            [task_id, agent_ids, checksum_wallets, shares_bps],
        )
        return "0x" + selector.hex() + encoded.hex()
    except Exception as exc:
        logger.warning("ABI encoding failed: %s", exc)
        return ""


def _onchain_prices_wei(agent_ids: list[str]) -> list[int] | None:
    """
    Query IdentityRegistry.getPricePerTask() on-chain for each agent.
    Returns a list of wei prices (same order), or None if unreachable / any agent inactive.
    """
    try:
        from web3 import Web3
        from app.core.config import get_settings as _gs
        s = _gs()
        if not s.identity_registry_address or not s.rpc_url:
            return None
        w3 = Web3(Web3.HTTPProvider(s.rpc_url, request_kwargs={"timeout": 5}))
        if not w3.is_connected():
            return None
        _abi = [
            {"inputs": [{"name": "agentId_", "type": "string"}],
             "name": "isActive",
             "outputs": [{"name": "", "type": "bool"}],
             "stateMutability": "view", "type": "function"},
            {"inputs": [{"name": "agentId_", "type": "string"}],
             "name": "getPricePerTask",
             "outputs": [{"name": "", "type": "uint256"}],
             "stateMutability": "view", "type": "function"},
        ]
        ir = w3.eth.contract(
            address=Web3.to_checksum_address(s.identity_registry_address),
            abi=_abi,
        )
        prices = []
        for aid in agent_ids:
            if not ir.functions.isActive(aid).call():
                logger.warning("Agent %s not active on-chain — cannot compute required total", aid)
                return None
            prices.append(ir.functions.getPricePerTask(aid).call())
        return prices
    except Exception as exc:
        logger.warning("_onchain_prices_wei failed: %s", exc)
        return None


def _compute_purchase_info(enriched: list[dict], task_id: str, escrow_address: str) -> dict:
    """Compute pipeline purchase parameters for MetaMask depositPaymentPipeline call."""
    agent_ids = [e["agent_id"] for e in enriched]
    wallets   = [e["wallet"]   for e in enriched]
    prices_db = [e["price_per_task"] for e in enriched]  # ETH from DB
    n         = len(prices_db)

    # Use on-chain prices when available — EscrowManager calls getPricePerTask()
    # internally, so msg.value must equal exactly what the contract sums.
    onchain = _onchain_prices_wei(agent_ids)
    if onchain is not None:
        total_wei = sum(onchain)
        total_eth = total_wei / 1e18
        # Shares proportional to on-chain prices
        if total_wei > 0:
            raw = [round(p / total_wei * 10_000) for p in onchain]
        else:
            base = 10_000 // n if n else 10_000
            raw  = [base] * n
    else:
        # Fallback: DB prices (may differ from on-chain — transaction might still revert)
        total_eth = sum(prices_db)
        total_wei = int(total_eth * 1e18)
        if total_eth > 0 and n > 0:
            raw = [round(p / total_eth * 10_000) for p in prices_db]
        else:
            base = 10_000 // n if n else 10_000
            raw  = [base] * n

    # Ensure shares sum == 10000
    if raw:
        raw[-1] = 10_000 - sum(raw[:-1])

    call_data = _encode_deposit_pipeline_call(task_id, agent_ids, wallets, raw)

    return {
        "contract_address": escrow_address,
        "task_id":          task_id,
        "agent_ids":        agent_ids,
        "wallets":          wallets,
        "shares_bps":       raw,
        "total_eth":        total_eth,
        "total_eth_wei":    str(total_wei),
        "call_data":        call_data,
    }


# ── Background worker ─────────────────────────────────────────────────────────

async def _execute_and_track(task_id: str, plan_obj, matches: list, prompt: str, agent_params: dict = {}) -> None:
    from app.services.execution_service import execute_pipeline_task
    try:
        await execute_pipeline_task(task_id, plan_obj, matches, prompt, agent_params)
    except Exception as exc:
        logger.exception("Pipeline task %s failed: %s", task_id, exc)
        update_pipeline_task(task_id, status="failed")


# ── Request / Response models ─────────────────────────────────────────────────

class RunTaskRequest(BaseModel):
    prompt:       str
    buyer_wallet: str = ""
    agent_params: dict = {}


class RunTaskResponse(BaseModel):
    task_id: str
    mode:    str
    plan:    dict
    agents:  list[dict]
    status:  str


class PlanOnlyRequest(BaseModel):
    prompt:       str
    buyer_wallet: str = ""


class AlternativesRequest(BaseModel):
    subtask_description: str
    excluded_agent_ids:  list[str] = []
    limit:               int = 5


class PurchaseInfoRequest(BaseModel):
    task_id: str


class ExecuteRequest(BaseModel):
    task_id:      str
    # Optional: provided when coming from the select-pack flow (task not pre-stored in DB)
    prompt:       str = ""
    mode:         str = "pipeline"
    subtasks:     list[dict] = []
    agents:       list[dict] = []
    buyer_wallet: str = ""
    agent_params: dict = {}


class PackProposalsRequest(BaseModel):
    prompt:       str
    buyer_wallet: str = ""


class SelectPackRequest(BaseModel):
    pack_id:      str
    prompt:       str
    mode:         str
    reasoning:    str = ""
    subtasks:     list[dict]
    agents:       list[dict]  # enriched agent dicts from the selected pack
    buyer_wallet: str = ""
    pack_name:    str = ""


class ConfirmAccessRequest(BaseModel):
    buyer_wallet: str
    tx_hash:      str = ""


# ── Helpers for pack proposals ───────────────────────────────────────────────

def _enrich_stored_agents(agents_json: str | list | None) -> list[dict]:
    """Ensures agents in stored JSON always have their latest env_var_keys."""
    if not agents_json: return []
    try:
        agents = _json.loads(agents_json) if isinstance(agents_json, str) else agents_json
    except Exception:
        return []
    
    from app.db.identity_repo import get_agent_identity
    enriched = []
    for a in agents:
        agent_id = a.get("agent_id")
        if not agent_id:
            enriched.append(a)
            continue
            
        # If env_var_keys already exists and isn't empty, we could keep it, 
        # but re-fetching ensures we have the latest metadata.
        identity = get_agent_identity(agent_id) or {}
        meta_raw = identity.get("identity_metadata") or "{}"
        meta = _json.loads(meta_raw) if isinstance(meta_raw, str) else {}
        
        caps = meta.get("capabilities", {})
        sand = meta.get("sandbox_config", {})
        keys = _public_env_var_keys(
            caps.get("env_var_keys")
            or sand.get("env_var_keys")
            or meta.get("env_var_keys")
            or []
        )
        
        # Merge: keep old fields (scores, etc.) but update keys
        a["env_var_keys"] = keys
        enriched.append(a)
    return enriched


def _agents_to_matches(enriched: list[dict]) -> list[dict]:
    """Convert enriched agent dicts back to AgentMatch-compatible shape for DB storage."""
    return [
        {
            "subtask_id":   a.get("subtask_id", ""),
            "agent_id":     a["agent_id"],
            "cosine_score": a.get("cosine_score", 0.0),
            "trust_score":  a.get("trust_score", 0.0),
            "final_score":  a.get("final_score", 0.0),
        }
        for a in enriched
    ]


_VALIDATION_TERMINAL_STATUSES = {"validated", "rejected", "failed", "awaiting_run"}
_STALE_VALIDATION_AFTER = timedelta(minutes=10)


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _pipeline_agent_ids(task: dict) -> list[str]:
    agent_ids: list[str] = []
    for step in task.get("steps_json") or []:
        if step.get("status") != "success":
            continue
        aid = step.get("agent_id")
        if aid and aid not in agent_ids:
            agent_ids.append(aid)

    if not agent_ids:
        for item in task.get("selected_agents_json") or []:
            aid = item.get("agent_id")
            if aid and aid not in agent_ids:
                agent_ids.append(aid)
    return agent_ids


def _expected_pipeline_val_task_id(task_id: str, agent_id: str) -> str:
    return f"val-{task_id[:12]}-{agent_id[:8]}"


def _repair_stale_pipeline_validation(task: dict) -> dict:
    """Move orphaned judge validations out of in_progress so UI cannot spin forever."""
    if task.get("status") != "validating":
        return task

    from app.db import access_repo

    now = datetime.now(timezone.utc)
    changed = False
    terminal_count = 0
    agent_ids = _pipeline_agent_ids(task)

    for aid in agent_ids:
        expected_val_task_id = _expected_pipeline_val_task_id(task["id"], aid)
        session = access_repo.get_validation_session(aid) or {}
        belongs_to_task = session.get("val_task_id") == expected_val_task_id
        status = session.get("status") if belongs_to_task else None

        if status in _VALIDATION_TERMINAL_STATUSES:
            terminal_count += 1
            continue

        started_at = _parse_iso_datetime(session.get("started_at") if belongs_to_task else None)
        created_at = _parse_iso_datetime(task.get("created_at")) or now
        age_anchor = started_at or created_at
        if now - age_anchor < _STALE_VALIDATION_AFTER:
            continue

        verdicts = access_repo.get_judge_verdicts(aid) if belongs_to_task else []
        if not verdicts:
            access_repo.insert_judge_verdict(
                agent_id=aid,
                judge_id="validation-timeout",
                judge_name="Validation Timeout",
                score=0,
                justification=(
                    "Judge validation was interrupted or exceeded the backend timeout. "
                    "No judge container result was recorded."
                ),
                verdict="INVALID",
            )

        access_repo.upsert_validation_session(
            aid,
            val_task_id=expected_val_task_id,
            status="failed",
            consensus_verdict="INVALID",
            aggregated_score=0,
            finished_at=now.isoformat(),
        )
        terminal_count += 1
        changed = True
        logger.warning("Marked stale pipeline validation failed: task=%s agent=%s", task["id"], aid)

    if agent_ids and terminal_count == len(agent_ids):
        update_pipeline_task(task["id"], status="done", finished_at=now.isoformat())
        task = {**task, "status": "done", "finished_at": now.isoformat()}
        changed = True

    if changed:
        logger.warning("Repaired stale pipeline validation state for task=%s", task["id"])
    return task


def _pipeline_validation_results(task: dict) -> dict:
    """Return per-agent judge validation state for a pipeline status response."""
    from app.db import access_repo

    agent_ids = _pipeline_agent_ids(task)

    results = {}
    for aid in agent_ids:
        expected_val_task_id = _expected_pipeline_val_task_id(task["id"], aid)
        session = access_repo.get_validation_session(aid) or {}
        belongs_to_task = session.get("val_task_id") == expected_val_task_id
        verdicts = access_repo.get_judge_verdicts(aid) if belongs_to_task else []
        # Drop stale timeout entries if real judge verdicts also exist
        real = [v for v in verdicts if v["judge_id"] != "validation-timeout"]
        if real:
            verdicts = real
        results[aid] = {
            "status": session.get("status") if belongs_to_task else "not_started",
            "val_task_id": session.get("val_task_id") if belongs_to_task else expected_val_task_id,
            "consensus_verdict": session.get("consensus_verdict") if belongs_to_task else None,
            "aggregated_score": session.get("aggregated_score") if belongs_to_task else None,
            "started_at": session.get("started_at") if belongs_to_task else None,
            "finished_at": session.get("finished_at") if belongs_to_task else None,
            "judges": [
                {
                    "judge_id": v["judge_id"],
                    "judge_name": v["judge_name"],
                    "score": v["score"],
                    "verdict": v["verdict"],
                    "justification": v["justification"],
                }
                for v in verdicts
            ],
        }
    return results


async def _build_pack_proposals(prompt: str, trust_scores: dict) -> list[dict]:
    """
    Génère des propositions de packs à partir d'approches alternatives distinctes.
    Le LLM propose N approches différentes (solo, pipeline 2 agents, pipeline complet, etc.)
    selon ce qui fait sens pour la tâche — pas de quota fixe.
    """
    import dataclasses as dc

    alt_plans = await decompose_task_alternatives(prompt)
    proposals: list[dict] = []
    seen_combos: list[frozenset] = []

    for i, plan in enumerate(alt_plans):
        matches = select_agents(plan.subtasks, trust_scores)
        if not matches:
            continue

        # Dédoublonner par ensemble d'agents assignés
        combo_key = frozenset(m.agent_id for m in matches)
        if combo_key in seen_combos:
            continue
        seen_combos.append(combo_key)

        enriched      = _enrich_matches(matches)
        agent_ids     = [a["agent_id"] for a in enriched]
        onchain       = _onchain_prices_wei(agent_ids)
        if onchain is not None:
            for agent, price_wei in zip(enriched, onchain):
                agent["price_per_task_wei"] = int(price_wei)
                agent["price_per_task"]     = int(price_wei) / 1e18
        subtasks_data = [dc.asdict(st) for st in plan.subtasks]
        total_eth     = round(sum(a["price_per_task"] for a in enriched), 8)
        avg_score     = round(sum(a["final_score"] for a in enriched) / len(enriched), 3) if enriched else 0.0
        agent_names   = [a.get("agent_name") or a["agent_id"] for a in enriched]

        proposals.append({
            "pack_id":                f"pack-{i}",
            "name":                   plan.pack_name or " + ".join(dict.fromkeys(agent_names)),
            "description":            plan.pack_rationale or " → ".join(agent_names),
            "agents":                 enriched,
            "subtasks":               subtasks_data,
            "total_eth":              total_eth,
            "quality_score":          avg_score,
            "estimated_duration_min": round(len(enriched) * 1.5, 1),
            "mode":                   plan.mode,
        })

    return proposals


# ── POST /tasks/pack-proposals ───────────────────────────────────────────────

@router.post("/pack-proposals")
async def pack_proposals(body: PackProposalsRequest) -> JSONResponse:
    """
    Returns up to 3 pack options for a task:
      - Full Pipeline : best agents per subtask
      - Economy Pack  : cheapest agents per subtask (only if different from quality)
      - Solo Agent    : single best agent for the whole task
    No task is created in DB at this stage — call /select-pack to confirm.
    """
    if not body.prompt.strip():
        raise HTTPException(400, detail="prompt vide")

    # Calcul trust scores (sans besoin du plan standard)
    try:
        from app.services.eigentrust_service import compute_eigentrust
        from app.db.identity_repo import get_all_agent_identities
        from app.db.collaboration_repo import get_solo_scores, get_pipeline_scores

        all_ids = get_all_agent_identities()
        agents  = [
            {"agent_id": r["agent_id"], "token_id": r["current_token_id"]}
            for r in all_ids
            if r.get("current_token_id") and r.get("agent_type", 0) != 1
        ]
        p_overrides = {}
        for a in agents:
            scores = get_solo_scores(a["agent_id"]) or get_pipeline_scores(a["agent_id"])
            if scores:
                nonzero = [s for s in scores if s > 0]
                recent  = nonzero[-5:] if nonzero else []
                if recent:
                    p_overrides[a["agent_id"]] = sum(recent) / len(recent)
        et_result    = compute_eigentrust(agents, task_p_overrides=p_overrides or None)
        trust_scores = {
            aid: et_result.scores_by_agent[aid]["global_trust"]
            for aid in et_result.scores_by_agent
        }
    except Exception as exc:
        logger.warning("EigenTrust indisponible pour pack-proposals : %s", exc)
        trust_scores = {}

    packs = await _build_pack_proposals(body.prompt, trust_scores)

    if not packs:
        raise HTTPException(503, detail="Aucun agent disponible pour construire des packs")

    return JSONResponse({"packs": packs, "reasoning": ""})


# ── POST /tasks/select-pack ───────────────────────────────────────────────────

@router.post("/select-pack")
async def select_pack(body: SelectPackRequest) -> JSONResponse:
    """
    User confirmed a pack.
    Creates the DB record immediately (access confirmed later via /confirm-access).
    Returns task_id and purchase_info for the MetaMask depositPaymentPipeline call.
    """
    if not body.subtasks or not body.agents:
        raise HTTPException(400, detail="subtasks et agents requis")

    import dataclasses
    from app.services.planner_service import SubTask
    from app.services.matching_service import AgentMatch

    task_id = str(uuid.uuid4())

    # Create DB record right away so access can be confirmed after payment
    create_pipeline_task(
        task_id=task_id,
        task_prompt=body.prompt,
        mode=body.mode,
        buyer_wallet=body.buyer_wallet,
    )
    subtasks_data = [
        {k: v for k, v in st.items() if k in ("id", "description", "domain", "depends_on", "complexity")}
        for st in body.subtasks
    ]
    agents_data = [
        {k: v for k, v in a.items()}
        for a in body.agents
    ]
    update_pipeline_task(
        task_id,
        plan_json=_json.dumps(subtasks_data),
        selected_agents_json=_json.dumps(agents_data),
        pack_id=body.pack_id,
        pack_name=body.pack_name or body.pack_id,
        status="plan_ready",
    )

    from app.core.config import get_settings
    purchase_info = _compute_purchase_info(body.agents, task_id, get_settings().escrow_manager_address)

    return JSONResponse({
        "task_id":       task_id,
        "mode":          body.mode,
        "purchase_info": purchase_info,
    })


# ── POST /tasks/{task_id}/confirm-access ──────────────────────────────────────

@router.post("/{task_id}/confirm-access")
async def confirm_pack_access(task_id: str, body: ConfirmAccessRequest) -> JSONResponse:
    """
    Called by the frontend after MetaMask payment is confirmed.
    Records access grant with 30-day expiry — same model as solo-agent AccessGrant.
    """
    from datetime import datetime, timedelta, timezone

    task = get_pipeline_task(task_id)
    if not task:
        raise HTTPException(404, detail=f"Tâche {task_id!r} introuvable")

    if task.get("buyer_wallet", "").lower() != body.buyer_wallet.lower():
        raise HTTPException(403, detail="Wallet mismatch")

    # Verify pipeline payment exists on-chain before granting access
    from app.db.escrow_repo import get_escrow_events_for_task
    onchain = get_escrow_events_for_task(task_id)
    if not any(e["event_type"] == "pipeline_deposited" for e in onchain):
        raise HTTPException(402, detail="Paiement pipeline non trouvé on-chain — attendez la confirmation du bloc")

    from app.core.config import get_settings
    access_duration = getattr(get_settings(), "pack_access_duration_days", 30)

    now     = datetime.now(timezone.utc)
    expires = now + timedelta(days=access_duration)

    update_pipeline_task(
        task_id,
        access_granted_at=now.isoformat(),
        access_expires_at=expires.isoformat(),
        tx_hash=body.tx_hash or "",
    )

    return JSONResponse({
        "task_id":          task_id,
        "access_granted_at": now.isoformat(),
        "access_expires_at": expires.isoformat(),
        "access_duration_days": access_duration,
    })


# ── GET /tasks/{task_id}/access ───────────────────────────────────────────────

@router.get("/{task_id}/access")
async def check_pack_access(task_id: str, buyer_wallet: str) -> JSONResponse:
    """
    Returns whether a buyer wallet has valid (non-expired) access to this pack task.
    Mirrors agentApi.checkAccess() for solo agents.
    """
    from datetime import datetime, timezone

    task = get_pipeline_task(task_id)
    if not task:
        return JSONResponse({"has_access": False, "reason": "not_found"})

    if task.get("buyer_wallet", "").lower() != buyer_wallet.lower():
        return JSONResponse({"has_access": False, "reason": "wallet_mismatch"})

    expires_str = task.get("access_expires_at")
    if not expires_str:
        return JSONResponse({"has_access": False, "reason": "not_paid"})

    try:
        expires_dt = datetime.fromisoformat(expires_str)
        if expires_dt.tzinfo is None:
            from datetime import timezone
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return JSONResponse({"has_access": False, "reason": "invalid_date"})

    if datetime.now(timezone.utc) > expires_dt:
        return JSONResponse({"has_access": False, "reason": "expired", "expired_at": expires_str})

    task = _repair_stale_pipeline_validation(task)
    return JSONResponse({
        "has_access":        True,
        "task_id":           task_id,
        "pack_id":           task.get("pack_id"),
        "pack_name":         task.get("pack_name"),
        "access_granted_at": task.get("access_granted_at"),
        "access_expires_at": expires_str,
        "status":            task.get("status"),
        "final_output":      task.get("final_output"),
        "steps_json":        task.get("steps_json"),
        "val_task_id":       task.get("val_task_id"),
        "validation_results": _pipeline_validation_results(task),
        "mode":              task.get("mode"),
        "task_prompt":       task.get("task_prompt"),
        "plan_json":         task.get("plan_json"),
        "selected_agents_json": _enrich_stored_agents(task.get("selected_agents_json")),
    })


# ── POST /tasks/plan-only ─────────────────────────────────────────────────────

@router.post("/plan-only")
async def plan_only(body: PlanOnlyRequest) -> JSONResponse:
    """
    Preview: planner + matching without execution.
    Returns plan, enriched agent data, and purchase_info for depositPaymentPipeline.
    """
    if not body.prompt.strip():
        raise HTTPException(400, detail="prompt vide")

    plan, matches, _ = await _run_planner_and_matching(body.prompt)

    import dataclasses
    task_id = str(uuid.uuid4())
    create_pipeline_task(
        task_id=task_id,
        task_prompt=body.prompt,
        mode=plan.mode,
        buyer_wallet=body.buyer_wallet,
    )
    update_pipeline_task(
        task_id,
        plan_json=[dataclasses.asdict(st) for st in plan.subtasks],
        selected_agents_json=[dataclasses.asdict(m) for m in matches],
        status="plan_ready",
    )

    enriched = _enrich_matches(matches)

    from app.core.config import get_settings
    purchase_info = _compute_purchase_info(enriched, task_id, get_settings().escrow_manager_address)

    return JSONResponse({
        "task_id":       task_id,
        "mode":          plan.mode,
        "reasoning":     plan.reasoning,
        "subtasks":      [dataclasses.asdict(st) for st in plan.subtasks],
        "agents":        enriched,
        "purchase_info": purchase_info,
    })


# ── POST /tasks/alternatives ──────────────────────────────────────────────────

@router.post("/alternatives")
async def get_alternatives(body: AlternativesRequest) -> JSONResponse:
    """Ranked alternative agents for a given subtask description."""
    if not body.subtask_description.strip():
        raise HTTPException(400, detail="subtask_description vide")

    try:
        from app.services.matching_service import (
            compute_embedding, cosine_similarity, _load_agents_with_embeddings,
        )
        from app.services.eigentrust_service import compute_eigentrust
        from app.db.identity_repo import get_all_agent_identities, get_agent_identity
        from app.db.collaboration_repo import get_solo_scores, get_pipeline_scores

        all_ids = get_all_agent_identities()
        agents  = [
            {"agent_id": r["agent_id"], "token_id": r["current_token_id"]}
            for r in all_ids
            if r.get("current_token_id") and r.get("agent_type", 0) != 1
        ]
        p_overrides = {}
        for a in agents:
            scores = get_solo_scores(a["agent_id"]) or get_pipeline_scores(a["agent_id"])
            if scores:
                nonzero = [s for s in scores if s > 0]
                recent  = nonzero[-5:] if nonzero else []
                if recent:
                    p_overrides[a["agent_id"]] = sum(recent) / len(recent)

        et_result    = compute_eigentrust(agents, task_p_overrides=p_overrides or None)
        trust_scores = {
            aid: et_result.scores_by_agent[aid]["global_trust"]
            for aid in et_result.scores_by_agent
        }

        st_emb     = compute_embedding(body.subtask_description)
        candidates = _load_agents_with_embeddings()

        scored = []
        for agent in candidates:
            aid = agent["agent_id"]
            if aid in body.excluded_agent_ids:
                continue
            cos   = cosine_similarity(st_emb, agent["embedding"])
            trust = trust_scores.get(aid, 0.0)
            score = COSINE_WEIGHT * cos + EIGENTRUST_WEIGHT * trust

            identity = get_agent_identity(aid) or {}
            meta_raw = identity.get("identity_metadata") or "{}"
            meta     = _json.loads(meta_raw) if isinstance(meta_raw, str) else {}
            price    = float(identity.get("price_per_task") or 0.0)

            scored.append({
                "agent_id":       aid,
                "agent_name":     identity.get("name") or meta.get("name") or aid,
                "description":    meta.get("description") or "",
                "cosine_score":   round(cos, 4),
                "trust_score":    round(trust, 4),
                "final_score":    round(score, 4),
                "price_per_task": price,
                "wallet":         identity.get("owner_address") or "",
            })

        scored.sort(key=lambda x: x["final_score"], reverse=True)
        return JSONResponse({"alternatives": scored[: body.limit]})

    except Exception as exc:
        logger.error("alternatives error: %s", exc)
        raise HTTPException(503, detail=str(exc))


# ── POST /tasks/pipeline-purchase-info ───────────────────────────────────────

@router.post("/pipeline-purchase-info")
async def pipeline_purchase_info(body: PurchaseInfoRequest) -> JSONResponse:
    """
    Returns depositPaymentPipeline parameters for a plan-ready task.
    Frontend passes these directly to MetaMask.
    """
    task = get_pipeline_task(body.task_id)
    if not task:
        raise HTTPException(404, detail=f"Tâche {body.task_id!r} introuvable")

    selected = task.get("selected_agents_json") or []
    if not selected:
        raise HTTPException(400, detail="Aucun agent sélectionné pour cette tâche")

    from app.db.identity_repo import get_agent_identity
    from app.core.config import get_settings

    enriched = []
    for m in selected:
        agent_id = m.get("agent_id", "")
        identity = get_agent_identity(agent_id) or {}
        meta_raw = identity.get("identity_metadata") or "{}"
        meta     = _json.loads(meta_raw) if isinstance(meta_raw, str) else {}
        price    = float(identity.get("price_per_task") or 0.0)
        enriched.append({
            "agent_id":       agent_id,
            "agent_name":     identity.get("name") or meta.get("name") or agent_id,
            "price_per_task": price,
            "wallet":         identity.get("owner_address") or "",
        })

    purchase_info = _compute_purchase_info(enriched, body.task_id, get_settings().escrow_manager_address)
    return JSONResponse(purchase_info)


# ── POST /tasks/execute ───────────────────────────────────────────────────────

_SUBTASK_FIELDS      = {"id", "domain", "description", "depends_on", "output_type"}
_AGENT_MATCH_FIELDS  = {"subtask_id", "agent_id", "cosine_score", "trust_score", "final_score"}


@router.post("/execute")
async def execute_task(body: ExecuteRequest, bg: BackgroundTasks) -> JSONResponse:
    """
    Start execution of a task.
    Two flows supported:
      - plan-only flow: task was pre-stored in DB (task_id found in DB)
      - select-pack flow: task not in DB; subtasks + agents come from the request body
        and the DB record is created here (right before execution starts)
    """
    from app.services.planner_service import TaskPlan, SubTask
    from app.services.matching_service import AgentMatch

    task = get_pipeline_task(body.task_id)

    if task:
        # Allow re-running a completed task (from active packs Live Test)
        if task.get("status") not in ("plan_ready", "failed", "done", "validating"):
            raise HTTPException(400, detail=f"Statut invalide: {task.get('status')!r}")
        subtasks_data = task.get("plan_json") or []
        matches_data  = task.get("selected_agents_json") or []
        # Parse if stored as JSON strings (list_pipeline_tasks doesn't auto-parse)
        if isinstance(subtasks_data, str):
            subtasks_data = _json.loads(subtasks_data) or []
        if isinstance(matches_data, str):
            matches_data = _json.loads(matches_data) or []
        prompt = task.get("task_prompt") or body.prompt
        mode   = task.get("mode") or body.mode
    else:
        if not body.subtasks or not body.agents:
            raise HTTPException(404, detail=f"Tâche {body.task_id!r} introuvable et aucun plan fourni")
        subtasks_data = body.subtasks
        matches_data  = _agents_to_matches(body.agents)
        prompt = body.prompt
        mode   = body.mode
        create_pipeline_task(
            task_id=body.task_id,
            task_prompt=prompt,
            mode=mode,
            buyer_wallet=body.buyer_wallet,
        )
        update_pipeline_task(
            body.task_id,
            plan_json=subtasks_data,
            selected_agents_json=matches_data,
            status="plan_ready",
        )

    if not subtasks_data:
        raise HTTPException(400, detail="Aucun plan pour cette tâche")

    # Filter to only the fields each dataclass accepts — stored dicts may contain
    # extra metadata (agent_name, price_per_task, wallet, complexity, …)
    subtasks = [
        SubTask(**{k: v for k, v in st.items() if k in _SUBTASK_FIELDS})
        for st in subtasks_data
    ]
    matches = [
        AgentMatch(**{k: v for k, v in m.items() if k in _AGENT_MATCH_FIELDS})
        for m in matches_data
    ]
    plan_obj = TaskPlan(mode=mode, subtasks=subtasks, reasoning="")

    # Clear previous run's output so polling never returns stale data
    update_pipeline_task(body.task_id, status="executing", final_output="", steps_json=[])
    bg.add_task(_execute_and_track, body.task_id, plan_obj, matches, prompt, body.agent_params)

    return JSONResponse({"task_id": body.task_id, "status": "executing"})


# ── POST /tasks/run ───────────────────────────────────────────────────────────

@router.post("/run", response_model=RunTaskResponse)
async def run_task(body: RunTaskRequest, bg: BackgroundTasks) -> RunTaskResponse:
    """
    Full pipeline: planner → matching → execution (background).
    Returns immediately with task_id + plan.
    """
    if not body.prompt.strip():
        raise HTTPException(400, detail="prompt ne peut pas être vide")

    plan, matches, _ = await _run_planner_and_matching(body.prompt)

    import dataclasses
    task_id = str(uuid.uuid4())
    create_pipeline_task(
        task_id=task_id,
        task_prompt=body.prompt,
        mode=plan.mode,
        buyer_wallet=body.buyer_wallet,
    )
    update_pipeline_task(
        task_id,
        plan_json=[dataclasses.asdict(st) for st in plan.subtasks],
        selected_agents_json=[dataclasses.asdict(m) for m in matches],
    )

    bg.add_task(_execute_and_track, task_id, plan, matches, body.prompt, body.agent_params)

    enriched = _enrich_matches(matches)
    return RunTaskResponse(
        task_id=task_id,
        mode=plan.mode,
        plan={
            "mode":      plan.mode,
            "reasoning": plan.reasoning,
            "subtasks":  [dataclasses.asdict(st) for st in plan.subtasks],
        },
        agents=enriched,
        status="executing",
    )


# ── GET /tasks/{task_id}/status ───────────────────────────────────────────────

@router.get("/{task_id}/status")
async def get_task_status(task_id: str) -> JSONResponse:
    """Poll the status of any pipeline task."""
    task = get_pipeline_task(task_id)
    if not task:
        raise HTTPException(404, detail=f"Tâche {task_id!r} introuvable")
    task = _repair_stale_pipeline_validation(task)
    return JSONResponse({
        "task_id":      task["id"],
        "mode":         task.get("mode"),
        "status":       task.get("status"),
        "steps":        task.get("steps_json") or [],
        "final_output": task.get("final_output"),
        "val_task_id":  task.get("val_task_id"),
        "validation_results": _pipeline_validation_results(task),
        "created_at":   task.get("created_at"),
        "finished_at":  task.get("finished_at"),
    })


# ── GET /tasks/ ───────────────────────────────────────────────────────────────

@router.get("/")
async def list_tasks(buyer_wallet: str = "", limit: int = 20) -> JSONResponse:
    """List recent tasks, optionally filtered by buyer_wallet."""
    tasks = list_pipeline_tasks(buyer_wallet=buyer_wallet or None, limit=limit)
    return JSONResponse({"tasks": tasks, "count": len(tasks)})

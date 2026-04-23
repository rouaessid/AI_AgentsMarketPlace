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


# InternalVote enum: NONE=0, VALID=1, INVALID=2
_VOTE_VALID   = 1
_VOTE_INVALID = 2

# ── Minimal ValidationRegistry ABI ───────────────────────────────────────────

_VALIDATION_ABI = [
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"providerAgentId_"},{"type":"string","name":"requestURI_"},{"type":"bytes32","name":"requestHash_"}],"name":"validationRequest","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string[]","name":"candidates_"}],"name":"assignJudges","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"judgeId_"},{"type":"bytes32","name":"commitHash_"}],"name":"commitVote","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"string","name":"judgeId_"},{"type":"uint8","name":"vote_"},{"type":"bytes32","name":"salt_"}],"name":"revealVote","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"type":"string","name":"taskId_"},{"type":"uint256","name":"aggregatedScore_"},{"type":"string","name":"justificationURI_"}],"name":"finaliseValidation","outputs":[],"stateMutability":"nonpayable","type":"function"},
]

# Minimal IdentityRegistry ABI — juste getAgentWallet
_IDENTITY_ABI = [
    {"inputs":[{"type":"string","name":"agentId_"}],"name":"getAgentWallet","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]


# ── Public entry point ────────────────────────────────────────────────────────

async def run_validation(
    agent_id:    str,
    val_task_id: str,
    proxy_cid:   str,
) -> None:
    """
    Full validation flow. Called as a FastAPI BackgroundTask after each Run.
    """
    logger.info("[val] START agent=%s task=%s cid=%s", agent_id, val_task_id, proxy_cid)

    access_repo.upsert_validation_session(
        agent_id, val_task_id=val_task_id,
        status="in_progress",
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    access_repo.clear_judge_verdicts(agent_id)

    # ── 1. Run judges — each fetches the trace from IPFS itself ──────────
    results = await _run_judges(proxy_cid)

    for r in results:
        access_repo.insert_judge_verdict(
            agent_id=agent_id,
            judge_id=r.judge_id,
            judge_name=r.judge_name,
            score=r.score,
            justification=r.justification,
            verdict=r.verdict,
        )
        logger.info("[val] %s → %s (%d/100)", r.judge_id, r.verdict, r.score)

    # ── 3. Consensus ──────────────────────────────────────────────────────
    valid_count      = sum(1 for r in results if r.verdict == "VALID")
    consensus        = "VALID" if valid_count >= 2 else "INVALID"
    aggregated_score = sum(r.score for r in results) // len(results)

    logger.info("[val] consensus=%s score=%d (%d/%d VALID)",
                consensus, aggregated_score, valid_count, len(results))

    # ── 4. On-chain commit-reveal (if configured) ─────────────────────────
    await _onchain_flow(agent_id, val_task_id, proxy_cid, results, aggregated_score)

    # ── 5. Persist final result ───────────────────────────────────────────
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
        logger.warning("[val] Could not update reputation metrics: %s", e)

    logger.info("[val] DONE agent=%s → %s", agent_id, final_status)


# ── Judge dispatch — registered containers only (no fallback) ────────────────

async def _run_judges(proxy_cid: str) -> list[JudgeResult]:
    """
    Run only registered judge agents (Docker containers).
    Built-in fallback is DISABLED — judges must be registered via the platform.

    If no judge agents are registered or fewer than 3 are available,
    validation is aborted and returns INVALID with an explicit error.
    This enforces the decentralized model: judges must be registered.
    """
    registered = _get_registered_judges()

    if not registered:
        logger.error("[val] No judge agents registered — validation cannot proceed. "
                     "Register at least one judge via the platform frontend.")
        return [JudgeResult(
            judge_id="no-judges",
            judge_name="No Judges",
            score=0,
            verdict="INVALID",
            justification=(
                "Validation aborted: no judge agents are registered on the platform. "
                "Register judge-alpha, judge-beta, and judge-gamma via the frontend."
            ),
        )]

    if len(registered) < 3:
        logger.warning("[val] Only %d judge(s) registered — need 3 for valid consensus.",
                       len(registered))

    logger.info("[val] Running %d registered judge(s)", len(registered))
    return await _run_registered_judges(proxy_cid, registered[:3])


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
    proxy_cid: str,
    judges: list,
) -> list[JudgeResult]:
    """
    Run each registered judge Docker container via the sandbox.
    Passes the raw IPFS CID as the prompt — the judge fetches the trace itself.
    Fully decentralized: judges are independent from the platform.
    """
    from app.services.sandbox_service import SandboxService

    svc   = SandboxService()
    tasks = [
        _run_one_judge(svc, judge, proxy_cid)
        for judge in judges
    ]
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


async def _run_one_judge(svc, judge_record, proxy_cid: str) -> JudgeResult:
    """
    Run a single judge container.
    The judge receives the raw IPFS CID — it fetches the trace itself.
    This is the fully decentralized contract: the judge provider only needs
    to know how to fetch from IPFS, nothing about the platform internals.
    """
    from app.services.sandbox_service import SandboxInput

    manifest = await svc.run_agent(
        judge_record,
        SandboxInput(
            task_id=f"judge-{uuid.uuid4().hex[:8]}",
            agent_id=judge_record.agent_id,
            task_prompt=proxy_cid,
        ),
        env_vars={
            "IPFS_GATEWAY": "http://host.docker.internal:8000/ipfs",
        },
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

    score   = max(0, min(100, int(output.get("score", 0))))
    verdict = "VALID" if str(output.get("verdict", "")).upper() == "VALID" else "INVALID"
    if score >= 60:
        verdict = "VALID"
    else:
        verdict = "INVALID"

    return JudgeResult(
        judge_id=output.get("judge_id", judge_record.agent_id),
        judge_name=judge_record.name,
        score=score,
        verdict=verdict,
        justification=output.get("justification", "No justification from judge container."),
    )



# ── Wallet → clé privée ───────────────────────────────────────────────────────

def _build_wallet_key_map() -> dict[str, str]:
    """
    Construit un dict {wallet_address_lower: private_key} depuis la config.
    Source primaire  : JUDGE_WALLET_KEYS (JSON dict dans .env)
    Source de repli  : JUDGE_1/2/3_PRIVATE_KEY (backwards-compat)
    """
    result: dict[str, str] = {}

    # Source primaire : dict explicite wallet → clé
    for raw_wallet, raw_key in settings.judge_wallet_keys.items():
        result[raw_wallet.lower()] = raw_key

    # Repli : dériver l'adresse depuis chaque clé configurée
    from eth_account import Account as EthAccount
    for key in [settings.judge_1_private_key,
                settings.judge_2_private_key,
                settings.judge_3_private_key]:
        if key:
            addr = EthAccount.from_key(key).address.lower()
            result.setdefault(addr, key)   # setdefault : ne pas écraser judge_wallet_keys

    return result


# ── On-chain commit-reveal ────────────────────────────────────────────────────

async def _onchain_flow(
    agent_id:         str,
    val_task_id:      str,
    proxy_cid:        str,
    results:          list[JudgeResult],
    aggregated_score: int,
) -> None:
    if not (settings.validation_registry_address and settings.platform_private_key
            and settings.identity_registry_address):
        logger.info("[val] On-chain disabled (missing config) — off-chain only")
        return

    try:
        w3 = Web3(Web3.HTTPProvider(settings.rpc_url))
        registry = w3.eth.contract(
            address=Web3.to_checksum_address(settings.validation_registry_address),
            abi=_VALIDATION_ABI,
        )

        req_hash = bytes(Web3.keccak(text=f"{agent_id}|{proxy_cid}"))
        ipfs_uri = f"ipfs://{proxy_cid}"

        # validationRequest
        _send(w3, settings.platform_private_key,
              registry.functions.validationRequest(val_task_id, agent_id, ipfs_uri, req_hash))
        await asyncio.sleep(1)

        # assignJudges — candidates from selector (contract does final eligibility + random pick)
        registered = _get_registered_judges()
        if len(registered) < 3:
            logger.error(
                "[val] Not enough registered judges (%d/3). On-chain flow aborted. "
                "Register judge-alpha, judge-beta, and judge-gamma via the platform.",
                len(registered),
            )
            return

        judge_ids = [j.agent_id for j in registered[:3]]

        _send(w3, settings.platform_private_key,
              registry.functions.assignJudges(val_task_id, judge_ids))
        await asyncio.sleep(1)

        # Résoudre wallet → clé privée pour chaque juge assigné
        # Chaque juge a l'adresse de celui qui l'a enregistré (son agentWallet)
        identity = w3.eth.contract(
            address=Web3.to_checksum_address(settings.identity_registry_address),
            abi=_IDENTITY_ABI,
        )
        wallet_key_map = _build_wallet_key_map()
        judge_keys = []
        for jid in judge_ids:
            wallet = identity.functions.getAgentWallet(jid).call().lower()
            key = wallet_key_map.get(wallet)
            if not key:
                raise RuntimeError(
                    f"Pas de clé privée configurée pour le wallet du juge {jid} ({wallet}). "
                    f"Ajoutez JUDGE_WALLET_KEYS={{'{wallet}':'0xCLÉ'}} dans .env"
                )
            judge_keys.append(key)

        _ensure_local_dev_judge_funding(w3, settings.platform_private_key, judge_keys)
        salts = []
        for res, key, jid in zip(results, judge_keys, judge_ids):
            vote  = _VOTE_VALID if res.verdict == "VALID" else _VOTE_INVALID
            salt  = secrets.token_bytes(32)
            salts.append(salt)
            chash = bytes(Web3.keccak(abi_encode(["uint8", "bytes32"], [vote, salt])))
            _send(w3, key, registry.functions.commitVote(val_task_id, jid, chash))
            await asyncio.sleep(0.5)

        # revealVote
        for res, key, jid, salt in zip(results, judge_keys, judge_ids, salts):
            vote = _VOTE_VALID if res.verdict == "VALID" else _VOTE_INVALID
            _send(w3, key, registry.functions.revealVote(val_task_id, jid, vote, salt))
            await asyncio.sleep(0.5)

        # finaliseValidation
        _send(w3, settings.platform_private_key,
              registry.functions.finaliseValidation(
                  val_task_id, aggregated_score, f"ipfs://val-{val_task_id}"
              ))
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


def _ensure_local_dev_judge_funding(
    w3: Web3,
    platform_private_key: str,
    judge_keys: list[str],
    min_balance_wei: int | None = None,
) -> None:
    if not _is_local_dev_chain(w3):
        return

    min_balance_wei = min_balance_wei or w3.to_wei(0.02, "ether")
    for key in judge_keys:
        judge = w3.eth.account.from_key(key)
        balance = w3.eth.get_balance(judge.address)
        if balance >= min_balance_wei:
            continue
        top_up = min_balance_wei - balance
        logger.warning("[val] Auto-funding local judge wallet %s with %s wei",
                       judge.address, top_up)
        _send_eth(w3, platform_private_key, judge.address, top_up)


def _is_local_dev_chain(w3: Web3) -> bool:
    endpoint = (settings.rpc_url or "").lower()
    return w3.eth.chain_id == settings.chain_id == 31337 and (
        "127.0.0.1" in endpoint or "localhost" in endpoint
    )


def _send_eth(w3: Web3, private_key: str, to_address: str, value_wei: int) -> str:
    account = w3.eth.account.from_key(private_key)
    nonce   = w3.eth.get_transaction_count(account.address, "pending")
    tx      = {
        "from": account.address,
        "to": Web3.to_checksum_address(to_address),
        "value": value_wei,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "gas": 21_000,
        "gasPrice": w3.eth.gas_price,
    }
    signed  = w3.eth.account.sign_transaction(tx, private_key)
    txh     = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(txh, timeout=60)
    if receipt["status"] != 1:
        raise RuntimeError(f"Funding TX reverted: {txh.hex()}")
    return txh.hex()

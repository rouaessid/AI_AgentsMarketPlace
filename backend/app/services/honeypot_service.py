"""
honeypot_service.py — Technical onboarding check for judge containers.

Purpose: verify the judge container is functional and protocol-compliant.
NOT a quality test — quality is guaranteed by stake/slash/consensus on-chain.

Checks performed:
  1. Container starts and responds to POST /run within timeout
  2. Response contains a valid score field
  3. Score is between 1 and 99 (not hardcoded 0 or 100)
  4. challenge_token is present in response (judge fetched trace from IPFS)
  5. trajectory_check is present in response (judge parsed the trace)

Called once at judge registration (POST /confirm).
After passing: judgeAuthorized = true on-chain → judge eligible for assignJudges().
"""
from __future__ import annotations

import logging
import secrets
import uuid

from web3 import Web3

from app.core.config import get_settings
from app.services.honeypot_store import TECHNICAL_TRACE

logger   = logging.getLogger(__name__)
settings = get_settings()

from app.core.abis import VALIDATION_REGISTRY_ABI as _HONEYPOT_ABI
from app.core.abis import IDENTITY_REGISTRY_ABI   as _IDENTITY_ABI

_HONEYPOT_CID_PREFIX = "QmTECHCHECK"


def _get_registry():
    if not settings.validation_registry_address:
        return None
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
    return w3.eth.contract(
        address=Web3.to_checksum_address(settings.validation_registry_address),
        abi=_HONEYPOT_ABI,
    )


def _resolve_judge_token_id(agent_id: str) -> int | None:
    """Resolve agentId string → current tokenId via IdentityRegistry."""
    if not settings.identity_registry_address or not settings.rpc_url:
        return None
    try:
        w3       = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 4}))
        identity = w3.eth.contract(
            address=Web3.to_checksum_address(settings.identity_registry_address),
            abi=_IDENTITY_ABI,
        )
        return int(identity.functions.getCurrentTokenId(agent_id).call())
    except Exception as exc:
        logger.warning("[onboarding] Could not resolve tokenId for %s: %s", agent_id, exc)
        return None


def _send_onchain(fn) -> str:
    if not (settings.validation_registry_address and settings.platform_private_key):
        return ""
    try:
        w3      = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
        account = w3.eth.account.from_key(settings.platform_private_key)
        nonce   = w3.eth.get_transaction_count(account.address, "pending")
        tx      = fn.build_transaction({
            "from": account.address, "nonce": nonce,
            "gas": 200_000, "gasPrice": w3.eth.gas_price,
        })
        signed  = w3.eth.account.sign_transaction(tx, settings.platform_private_key)
        txh     = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(txh, timeout=60)
        return txh.hex()
    except Exception as e:
        logger.warning("[onboarding] on-chain tx failed: %s", e)
        return ""


def _register_trace_in_proxy(fake_cid: str, trace: dict, challenge_token: str) -> None:
    try:
        from app.main import _HONEYPOT_CACHE
        from app.services.judge_service import _CHALLENGE_STORE
        _HONEYPOT_CACHE[fake_cid] = {**trace, "challenge_token": challenge_token}
        _CHALLENGE_STORE[fake_cid] = challenge_token
    except Exception as e:
        logger.warning("[onboarding] proxy registration failed: %s", e)


def _unregister_trace(fake_cid: str) -> None:
    try:
        from app.main import _HONEYPOT_CACHE
        from app.services.judge_service import _CHALLENGE_STORE
        _HONEYPOT_CACHE.pop(fake_cid, None)
        _CHALLENGE_STORE.pop(fake_cid, None)
    except Exception:
        pass


def _check_result(result: dict, challenge_token: str) -> tuple[bool, str]:
    """
    Run technical checks on the judge's response.
    Returns (passed, reason).
    """
    score = result.get("score")

    if score is None:
        return False, "no score in response"

    try:
        score = int(score)
    except (ValueError, TypeError):
        return False, f"score is not a number: {score}"

    if not (1 <= score <= 99):
        return False, f"score {score} out of range [1,99] — likely hardcoded"

    if not result.get("challenge_token"):
        return False, "challenge_token missing — judge did not fetch IPFS trace"

    if result.get("challenge_token") != challenge_token:
        return False, "challenge_token mismatch — judge did not fetch real trace"

    if not result.get("trajectory_check"):
        return False, "trajectory_check missing — judge did not parse trace"

    return True, "ok"


async def run_onboarding(judge_id: str) -> bool:
    """
    Technical onboarding check for a judge container.
    Called once at POST /confirm (async background task).

    Checks: container functional, protocol-compliant, not hardcoded.
    Does NOT test evaluation quality — that's handled by stake/slash/consensus.

    Returns True if onboarding passed.
    """
    # Already onboarded → skip
    if is_judge_authorized(judge_id):
        logger.info("[onboarding] %s already onboarded — skipping", judge_id)
        return True

    judge_record = _get_judge_record(judge_id)
    if not judge_record:
        logger.error("[onboarding] judge %s not found in cache", judge_id)
        return False

    fake_cid        = f"{_HONEYPOT_CID_PREFIX}_{uuid.uuid4().hex[:12]}"
    challenge_token = secrets.token_hex(8)

    _register_trace_in_proxy(fake_cid, TECHNICAL_TRACE, challenge_token)

    try:
        from app.services.sandbox_service import SandboxService, SandboxInput
        from app.services.judge_service import _judge_env

        svc    = SandboxService()
        result_raw = await _run_judge_container(svc, judge_record, fake_cid, _judge_env(judge_id))
        passed, reason = _check_result(result_raw, challenge_token)

        logger.info(
            "[onboarding] judge=%s passed=%s reason=%s score=%s",
            judge_id, passed, reason, result_raw.get("score"),
        )

        registry = _get_registry()
        result_cid = f"ipfs://onboarding-{judge_id}-{'pass' if passed else 'fail'}"

        if registry:
            judge_token_id = _resolve_judge_token_id(judge_id)
            if judge_token_id is not None:
                _send_onchain(registry.functions.recordHoneypotResult(
                    judge_token_id, passed, result_cid
                ))
            else:
                logger.warning("[onboarding] Skipping recordHoneypotResult — tokenId unresolved for %s", judge_id)

        # Mise à jour du registration_status en DB et en mémoire
        from app.repo.identity_repo import upsert_agent_identity
        from app.services.agent_service import _records, _agent_index
        from app.models.agent import AgentStatus

        new_status = AgentStatus.ACTIVE if passed else AgentStatus.VALIDATION_FAILED

        upsert_agent_identity(agent_id=judge_id, registration_status=new_status.value)
        rid = _agent_index.get(judge_id)
        if rid and rid in _records:
            _records[rid] = _records[rid].model_copy(update={"status": new_status})
            if passed:
                try:
                    rec = _records[rid]
                    if rec.registration_file:
                        import asyncio as _aio
                        from app.services.matching_service import embed_agent_capabilities
                        meta = rec.registration_file.model_dump()
                        _aio.get_event_loop().run_in_executor(
                            None, lambda: embed_agent_capabilities(judge_id, meta)
                        )
                except Exception as _e:
                    logger.warning("Embedding non calculé pour %s: %s", judge_id, _e)

        logger.info("[onboarding] %s → registration_status = %s", judge_id, new_status.value)
        return passed

    except Exception as e:
        logger.error("[onboarding] failed for %s: %s", judge_id, e)
        return False
    finally:
        _unregister_trace(fake_cid)


async def _run_judge_container(svc, judge_record, proxy_cid: str, env: dict) -> dict:
    """Run judge container and return raw output dict."""
    import json
    from app.services.sandbox_service import SandboxInput

    manifest = await svc.run_agent(
        judge_record,
        SandboxInput(
            task_id=f"onboarding-{uuid.uuid4().hex[:8]}",
            agent_id=judge_record.agent_id,
            task_prompt=proxy_cid,
        ),
        env_vars=env,
        use_proxy=False,
    )

    output = manifest.output or {}
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except Exception:
            output = {}
    if isinstance(output, dict) and "output" in output:
        output = output["output"]

    return output if isinstance(output, dict) else {}


def is_judge_authorized(judge_id: str) -> bool:
    """Read judgeOnboarded && !judgeFlagged from ValidationRegistry via RPC."""
    try:
        registry = _get_registry()
        if not registry:
            return True  # dev mode — no contract configured
        token_id = _resolve_judge_token_id(judge_id)
        if token_id is None:
            return True  # can't resolve → fail open
        return registry.functions.isJudgeAuthorized(token_id).call()
    except Exception as e:
        logger.warning("[onboarding] isJudgeAuthorized RPC failed: %s", e)
        return True  # fail open in dev


def _get_judge_record(judge_id: str):
    try:
        from app.services.agent_service import _records, _agent_index
        from app.models.agent import AgentType
        rid = _agent_index.get(judge_id)
        if not rid:
            return None
        record = _records.get(rid)
        if not record or record.agent_type != AgentType.JUDGE:
            return None
        return record
    except Exception:
        return None

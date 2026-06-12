"""
eigentrust_sync.py — Synchronisation EigenTrust on-chain.

Déclenché après chaque finaliseValidation() via compute_and_write_eigentrust().

Flux :
  finaliseValidation() on-chain
       ↓
  compute_and_write_eigentrust(agent_id, mode) — appelé depuis judge_service
       ↓
  ValidationRegistry.getAgentScore(agent_id).call() — score frais depuis blockchain
       ↓
  compute_eigentrust(agents, task_p_overrides={agent_id: fresh_score})
       ↓
  pour chaque agent dont le score a changé > THRESHOLD
       ↓
  ReputationRegistry.setEigenTrustScore(tokenId, score) — state variable directe
"""
from __future__ import annotations
import asyncio
import logging

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.core.config import get_settings
from app.repo.identity_repo import get_all_agent_identities
from app.services.eigentrust_service import compute_eigentrust

logger   = logging.getLogger(__name__)
settings = get_settings()

SCORE_CHANGE_THRESHOLD = 0.005

_last_scores: dict[str, float] = {}

from app.core.abis import REPUTATION_REGISTRY_ABI as _SET_EIGENTRUST_ABI


async def compute_and_write_eigentrust(agent_id: str, fresh_score: float) -> None:
    """Solo validation (mode=0) : déclenché par agent immédiatement après finalisation."""
    if not settings.reputation_registry_address or not settings.platform_private_key:
        return
    if fresh_score <= 0:
        logger.debug("EigenTrust ignoré : score=0 pour %s", agent_id)
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _compute_blocking, {agent_id: fresh_score})
    except Exception as e:
        logger.warning("EigenTrust non-bloquant échoué : %s", e)


async def refresh_all_eigentrust() -> None:
    """Post-startup refresh — recomputes EigenTrust for all agents with no overrides."""
    if not settings.reputation_registry_address or not settings.platform_private_key:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _compute_blocking, {})
    except Exception as e:
        logger.warning("EigenTrust refresh_all échoué : %s", e)


async def compute_and_write_eigentrust_pipeline(overrides: dict[str, float]) -> None:
    """Pipeline (mode=1) : déclenché une fois avec tous les agents du pipeline."""
    if not overrides:
        return
    if not settings.reputation_registry_address or not settings.platform_private_key:
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _compute_blocking, overrides)
    except Exception as e:
        logger.warning("EigenTrust pipeline non-bloquant échoué : %s", e)


def _compute_blocking(overrides: dict[str, float]) -> None:
    if not settings.rpc_url:
        return

    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        logger.warning("EigenTrust : nœud non disponible")
        return

    all_identities = get_all_agent_identities()
    agents = [
        {"agent_id": row["agent_id"], "token_id": row["current_token_id"]}
        for row in all_identities
        if row.get("current_token_id") and row.get("agent_type", 0) != 1
    ]
    if not agents:
        return

    result = compute_eigentrust(agents, task_p_overrides=overrides)
    if not result.scores_by_agent:
        return

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.reputation_registry_address),
        abi=_SET_EIGENTRUST_ABI,
    )
    account = Account.from_key(settings.platform_private_key)
    nonce   = w3.eth.get_transaction_count(account.address, "pending")

    written = 0
    for agent in agents:
        aid        = agent["agent_id"]
        token_id   = agent["token_id"]
        score_data = result.scores_by_agent.get(aid)
        if not score_data or not token_id:
            continue

        final_score = score_data["global_trust"]  # t[i] only — f[i] applied at read-time in reputation.py

        # Always refresh in-memory cache with the computed score
        try:
            from app.services.agent_service import refresh_reputation_score
            refresh_reputation_score(aid, final_score * 100.0)
        except Exception:
            pass

        if abs(final_score - _last_scores.get(aid, -1.0)) < SCORE_CHANGE_THRESHOLD:
            continue

        # final_score ∈ [0, 1] → uint256 × 10000 (4 decimals)
        score_uint = int(round(final_score * 10000))

        try:
            tx = contract.functions.setEigenTrustScore(
                token_id, score_uint
            ).build_transaction({
                "from":     account.address,
                "nonce":    nonce,
                "gas":      100_000,
                "gasPrice": w3.eth.gas_price,
            })
            signed  = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            _last_scores[aid] = final_score
            nonce  += 1
            written += 1
            logger.info("EigenTrust ✓ agent=%s score=%.4f tx=%s",
                        aid, final_score, tx_hash.hex()[:14])
        except Exception as e:
            logger.warning("setEigenTrustScore échoué pour %s : %s", aid, e)

    if written:
        logger.info("EigenTrust : %d agent(s) mis à jour", written)

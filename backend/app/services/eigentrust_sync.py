"""
eigentrust_sync.py — Synchronisation EigenTrust on-chain.

Déclenché après chaque ValidationResponse ou NewFeedback (tag1 ≠ "eigenTrust").
Calcule les scores EigenTrust pour tous les agents actifs et écrit
giveFeedback(tag1="eigenTrust") sur le ReputationRegistry signé par PLATFORM_KEY.

Flux :
  event capté par indexeur
       ↓
  sync_eigentrust_onchain() schedulé (asyncio task)
       ↓
  compute_eigentrust() → scores pour tous les agents
       ↓
  pour chaque agent dont le score a changé > THRESHOLD
       ↓
  giveFeedback(tag1="eigenTrust", value=score×1000, valueDecimals=3)
  signé par PLATFORM_KEY → envoyé on-chain
       ↓
  indexeur capte le NewFeedback → DB mise à jour automatiquement
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.core.config import get_settings
from app.db.identity_repo import get_all_agent_identities
from app.services.eigentrust_service import compute_eigentrust

logger   = logging.getLogger(__name__)
settings = get_settings()

# Seuil minimum de changement pour déclencher une écriture on-chain
# Évite les transactions inutiles quand le score varie très peu
SCORE_CHANGE_THRESHOLD = 0.005   # 0.5%

# Cache en mémoire des derniers scores écrits on-chain
# agent_id → final_score écrit lors de la dernière sync
_last_scores: dict[str, float] = {}

_GIVE_FEEDBACK_ABI = [
    {
        "inputs": [
            {"name": "agentTokenId",  "type": "uint256"},
            {"name": "value",         "type": "int128"},
            {"name": "valueDecimals", "type": "uint8"},
            {"name": "tag1",          "type": "string"},
            {"name": "tag2",          "type": "string"},
            {"name": "endpoint",      "type": "string"},
            {"name": "feedbackURI",   "type": "string"},
            {"name": "feedbackHash",  "type": "bytes32"},
        ],
        "name": "giveFeedback",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


async def sync_eigentrust_onchain() -> None:
    """
    Point d'entrée async — appelé depuis l'indexeur via asyncio.create_task().
    Délègue le travail bloquant (web3 + calcul) à un thread executor.
    Les erreurs sont loggées mais ne propagent pas (non-bloquant).
    """
    if not settings.reputation_registry_address:
        logger.debug("EigenTrust sync ignoré : REPUTATION_REGISTRY_ADDRESS non défini")
        return
    if not settings.feedback_wallet_key and not settings.platform_private_key:
        logger.debug("EigenTrust sync ignoré : aucun wallet de feedback configuré")
        return

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_blocking)
    except Exception as e:
        logger.warning("EigenTrust on-chain sync échoué (non-bloquant) : %s", e)


def _sync_blocking() -> None:
    """
    Calcule EigenTrust et écrit les scores on-chain pour les agents dont
    le score a changé depuis la dernière sync.
    """
    all_identities = get_all_agent_identities()
    agents = [
        {"agent_id": row["agent_id"], "token_id": row["current_token_id"]}
        for row in all_identities
        if row.get("current_token_id") and row.get("agent_type", 0) != 1
    ]

    if not agents:
        logger.debug("EigenTrust sync : aucun agent enregistré on-chain")
        return

    from app.db.collaboration_repo import get_solo_scores, get_pipeline_scores
    p_overrides = {}
    for a in agents:
        scores = get_solo_scores(a["agent_id"]) or get_pipeline_scores(a["agent_id"])
        if scores:
            nonzero = [s for s in scores if s > 0]
            recent  = nonzero[-5:] if nonzero else []
            if recent:
                p_overrides[a["agent_id"]] = sum(recent) / len(recent)

    result = compute_eigentrust(agents, task_p_overrides=p_overrides or None)
    if not result.scores_by_agent:
        return

    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        logger.warning("EigenTrust sync : nœud non disponible")
        return

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.reputation_registry_address),
        abi=_GIVE_FEEDBACK_ABI,
    )
    # Use feedback_wallet_key — NOT platform key (platform owns all tokens → AgentOwnerCannotRate)
    signing_key = settings.feedback_wallet_key or settings.platform_private_key
    account = Account.from_key(signing_key)
    nonce   = w3.eth.get_transaction_count(account.address, "pending")

    written = 0
    for agent in agents:
        agent_id   = agent["agent_id"]
        token_id   = agent["token_id"]
        score_data = result.scores_by_agent.get(agent_id)
        if not score_data:
            continue

        final_score = score_data["final_score"]
        last_score  = _last_scores.get(agent_id, -1.0)

        if abs(final_score - last_score) < SCORE_CHANGE_THRESHOLD:
            continue  # score inchangé — pas de tx inutile

        # final_score ∈ [0, 1] → value = score × 1000, valueDecimals = 3
        # ex: 0.15 → value=150, decimals=3 → 150/10³ = 0.150
        value = int(round(final_score * 1000))

        try:
            tx = contract.functions.giveFeedback(
                token_id,
                value,
                3,             # valueDecimals
                "eigenTrust",
                "",            # tag2
                "",            # endpoint
                "",            # feedbackURI
                b"\x00" * 32,  # feedbackHash
            ).build_transaction({
                "from":     account.address,
                "nonce":    nonce,
                "gas":      200_000,
                "gasPrice": w3.eth.gas_price,
            })

            signed  = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

            _last_scores[agent_id] = final_score
            nonce  += 1
            written += 1
            logger.info(
                "EigenTrust sync ✓ agent=%s score=%.4f tx=%s",
                agent_id, final_score, tx_hash.hex()[:14],
            )

        except Exception as e:
            logger.warning("EigenTrust sync échoué pour agent %s : %s", agent_id, e)

    if written:
        logger.info("EigenTrust sync : %d agent(s) mis à jour on-chain", written)
    else:
        logger.debug("EigenTrust sync : aucun score modifié (seuil %.1f%%)", SCORE_CHANGE_THRESHOLD * 100)

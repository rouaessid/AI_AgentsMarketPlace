"""
blockchain_service.py — Lecture blockchain + actions PLATFORM (pipeline scores).

Toutes les actions USER (register, stake, giveFeedback, mintNewVersion)
sont signées par MetaMask côté frontend — le backend ne signe jamais pour l'utilisateur.

Seules actions plateforme restantes :
  - record_pipeline_scores() : écrit les scores du pipeline après exécution automatique
"""
from __future__ import annotations
import logging

from web3 import Web3
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

# ABI minimal pour encoder register() (utilisé par _build_register_tx dans agent_service)
_IDENTITY_ABI = [
    {
        "inputs": [
            {"internalType": "string",  "name": "agentId_",      "type": "string"},
            {"internalType": "uint8",   "name": "agentType_",    "type": "uint8"},
            {"internalType": "string",  "name": "agentURI_",     "type": "string"},
            {"internalType": "string",  "name": "version_",      "type": "string"},
            {"internalType": "uint256", "name": "pricePerTask_", "type": "uint256"},
        ],
        "name": "register",
        "outputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "agentId_",    "type": "string"},
            {"internalType": "string", "name": "newURI_",     "type": "string"},
            {"internalType": "string", "name": "newVersion_", "type": "string"},
        ],
        "name": "mintNewVersion",
        "outputs": [{"internalType": "uint256", "name": "newTokenId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class BlockchainService:
    """Actions plateforme uniquement — ne signe jamais pour un utilisateur."""

    def __init__(self):
        self._w3: Web3 | None = None

    @property
    def w3(self) -> Web3:
        if self._w3 is None:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._w3 = w3
        return self._w3

    def is_available(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception as exc:
            logger.warning("Blockchain not reachable: %s", exc)
            return False

    def _account(self):
        from eth_account import Account
        return Account.from_key(settings.platform_private_key)

    def _send(self, fn, gas: int = 300_000) -> str:
        account = self._account()
        nonce   = self.w3.eth.get_transaction_count(account.address, "pending")
        tx      = fn.build_transaction({
            "from": account.address, "nonce": nonce,
            "gas": gas, "gasPrice": self.w3.eth.gas_price,
        })
        signed  = self.w3.eth.account.sign_transaction(tx, private_key=settings.platform_private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        if receipt.status != 1:
            raise RuntimeError(f"TX reverted: {tx_hash.hex()}")
        return tx_hash.hex()

    def record_pipeline_scores(
        self,
        task_id:   str,
        agent_ids: list[str],
        scores:    list[float],
    ) -> str:
        """
        Appelle ValidationRegistry.recordPipelineScores() après l'exécution d'un pipeline.
        Action automatique de la plateforme — pas une action utilisateur.
        Retourne tx_hash_hex ou "" en cas d'échec.
        """
        addr = settings.validation_registry_address
        if not addr:
            logger.warning("VALIDATION_REGISTRY_ADDRESS not set — skip recordPipelineScores")
            return ""
        if not settings.platform_private_key:
            logger.warning("PLATFORM_PRIVATE_KEY not set — skip recordPipelineScores")
            return ""
        if not self.is_available():
            return ""
        if not agent_ids or not scores or len(agent_ids) != len(scores):
            return ""

        _abi = [{
            "inputs": [
                {"name": "agentIds_", "type": "string[]"},
                {"name": "taskId_",   "type": "string"},
                {"name": "scores_",   "type": "uint8[]"},
            ],
            "name": "recordPipelineScores",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        }]

        try:
            uint8_scores = [max(0, min(100, int(round(s)))) for s in scores]
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(addr), abi=_abi
            )
            tx_hash = self._send(
                contract.functions.recordPipelineScores(agent_ids, task_id, uint8_scores)
            )
            logger.info("recordPipelineScores: task=%s agents=%s tx=%s",
                        task_id, agent_ids, tx_hash[:20])
            return tx_hash
        except Exception as exc:
            logger.error("record_pipeline_scores failed: %s", exc)
            return ""

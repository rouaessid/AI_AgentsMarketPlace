"""
blockchain_service.py — Platform-side on-chain interactions.

The platform signs and submits all transactions using PLATFORM_PRIVATE_KEY.
Works with the local Hardhat node (chain 31337) or any EVM-compatible RPC.
If the RPC is unreachable the service degrades gracefully (returns empty strings).
"""
from __future__ import annotations
import logging

from web3 import Web3
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Minimal ABIs ──────────────────────────────────────────────────────────────

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
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "internalType": "string",  "name": "agentId",   "type": "string"},
            {"indexed": True,  "internalType": "uint256", "name": "tokenId",   "type": "uint256"},
            {"indexed": True,  "internalType": "address", "name": "owner",     "type": "address"},
            {"indexed": False, "internalType": "uint8",   "name": "agentType", "type": "uint8"},
            {"indexed": False, "internalType": "string",  "name": "agentURI",  "type": "string"},
            {"indexed": False, "internalType": "string",  "name": "version",   "type": "string"},
        ],
        "name": "AgentCreated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "internalType": "string",  "name": "agentId",         "type": "string"},
            {"indexed": True,  "internalType": "uint256", "name": "newTokenId",       "type": "uint256"},
            {"indexed": True,  "internalType": "uint256", "name": "previousTokenId",  "type": "uint256"},
            {"indexed": False, "internalType": "string",  "name": "agentURI",         "type": "string"},
            {"indexed": False, "internalType": "string",  "name": "version",          "type": "string"},
        ],
        "name": "AgentVersionMinted",
        "type": "event",
    },
]

_STAKING_ABI = [
    {
        "inputs": [],
        "name": "stake",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "internalType": "address", "name": "agent",  "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "Staked",
        "type": "event",
    },
]


class BlockchainService:
    """
    Wraps IdentityRegistry and StakingContract calls.
    Uses the platform private key — all agents are owned by the platform wallet on-chain.
    Gracefully returns ("", 0) if the node is not reachable or key is missing.
    """

    def __init__(self):
        self._w3: Web3 | None = None

    # ── Connection ───────────────────────────────────────────────────────────

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
            ok = self.w3.is_connected() and bool(settings.platform_private_key)
            if ok:
                logger.debug("Blockchain available: chain=%d", self.w3.eth.chain_id)
            return ok
        except Exception as exc:
            logger.warning("Blockchain not reachable: %s", exc)
            return False

    def _account(self):
        from eth_account import Account
        return Account.from_key(settings.platform_private_key)

    def _send(self, tx: dict) -> "web3.types.HexBytes":
        """Sign + broadcast + wait for receipt. Raises on revert."""
        account = self._account()
        tx.setdefault("from",     account.address)
        tx.setdefault("chainId",  self.w3.eth.chain_id)
        tx.setdefault("gasPrice", self.w3.eth.gas_price)
        if "nonce" not in tx:
            tx["nonce"] = self.w3.eth.get_transaction_count(account.address, "pending")
        if "gas" not in tx:
            try:
                tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.3)
            except Exception:
                tx["gas"] = 400_000
        signed  = self.w3.eth.account.sign_transaction(tx, private_key=settings.platform_private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        if receipt.status != 1:
            raise RuntimeError(f"TX reverted: {tx_hash.hex()}")
        return tx_hash

    # ── IdentityRegistry.register() ─────────────────────────────────────────

    def register_agent(
        self,
        agent_id:       str,
        agent_type:     int,
        agent_uri:      str,
        version:        str,
        price_per_task: float = 0.0,
    ) -> tuple[str, int]:
        """
        Call IdentityRegistry.register(agentId, agentType, agentURI, version, pricePerTask).
        Returns (tx_hash_hex, token_id).
        Returns ("", 0) if blockchain unavailable or address not set.
        """
        addr = settings.identity_registry_address
        if not addr or addr.startswith("0x_"):
            logger.warning("IDENTITY_REGISTRY_ADDRESS not set — skipping on-chain register")
            return "", 0
        if not self.is_available():
            return "", 0

        price_wei = int(price_per_task * 10**18)

        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(addr),
                abi=_IDENTITY_ABI,
            )
            tx = contract.functions.register(
                agent_id, agent_type, agent_uri, version, price_wei
            ).build_transaction({
                "from":     self._account().address,
                "chainId":  self.w3.eth.chain_id,
                "nonce":    self.w3.eth.get_transaction_count(self._account().address, "pending"),
                "gasPrice": self.w3.eth.gas_price,
            })
            signed  = self.w3.eth.account.sign_transaction(tx, private_key=settings.platform_private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt.status != 1:
                raise RuntimeError(f"register() reverted: {tx_hash.hex()}")

            token_id = 0
            try:
                events = contract.events.AgentCreated().process_receipt(receipt)
                if events:
                    token_id = int(events[0]["args"]["tokenId"])
            except Exception as e:
                logger.warning("Could not parse AgentCreated event: %s", e)

            logger.info(
                "IdentityRegistry.register(%s) → tokenId=%d  tx=%s",
                agent_id, token_id, tx_hash.hex()[:20],
            )
            return tx_hash.hex(), token_id

        except Exception as exc:
            logger.error("register_agent failed: %s", exc)
            return "", 0

    # ── IdentityRegistry.mintNewVersion() ───────────────────────────────────

    def mint_new_version(self, agent_id: str, new_uri: str, new_version: str) -> tuple[str, int]:
        """
        Call IdentityRegistry.mintNewVersion(agentId_, newURI_, newVersion_).
        Mints a new NFT for the same agent_id — same logical agent, new token_id.
        Returns (tx_hash_hex, new_token_id), or ("", 0) on failure.
        """
        addr = settings.identity_registry_address
        if not addr or addr.startswith("0x_"):
            logger.warning("IDENTITY_REGISTRY_ADDRESS not set — skipping mintNewVersion")
            return "", 0
        if not self.is_available():
            return "", 0

        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(addr),
                abi=_IDENTITY_ABI,
            )
            tx = contract.functions.mintNewVersion(
                agent_id, new_uri, new_version
            ).build_transaction({
                "from":     self._account().address,
                "chainId":  self.w3.eth.chain_id,
                "nonce":    self.w3.eth.get_transaction_count(self._account().address, "pending"),
                "gasPrice": self.w3.eth.gas_price,
            })
            signed  = self.w3.eth.account.sign_transaction(tx, private_key=settings.platform_private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt.status != 1:
                raise RuntimeError(f"mintNewVersion() reverted: {tx_hash.hex()}")

            new_token_id = 0
            try:
                events = contract.events.AgentVersionMinted().process_receipt(receipt)
                if events:
                    new_token_id = int(events[0]["args"]["newTokenId"])
            except Exception as e:
                logger.warning("Could not parse AgentVersionMinted event: %s", e)

            logger.info(
                "IdentityRegistry.mintNewVersion(%s) → newTokenId=%d  tx=%s",
                agent_id, new_token_id, tx_hash.hex()[:20],
            )
            return tx_hash.hex(), new_token_id

        except Exception as exc:
            logger.error("mint_new_version failed: %s", exc)
            return "", 0

    # ── StakingContract.stake() ──────────────────────────────────────────────

    def stake(self, amount_eth: float) -> str:
        """
        Call StakingContract.stake() sending `amount_eth` ETH.
        Returns tx_hash_hex, or "" if unavailable / amount == 0.
        """
        addr = settings.staking_contract_address
        if not addr or amount_eth <= 0:
            return ""
        if not self.is_available():
            return ""

        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(addr),
                abi=_STAKING_ABI,
            )
            value_wei = self.w3.to_wei(amount_eth, "ether")
            tx = contract.functions.stake().build_transaction({
                "from":     self._account().address,
                "value":    value_wei,
                "chainId":  self.w3.eth.chain_id,
                "nonce":    self.w3.eth.get_transaction_count(self._account().address, "pending"),
                "gasPrice": self.w3.eth.gas_price,
            })
            signed  = self.w3.eth.account.sign_transaction(tx, private_key=settings.platform_private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt.status != 1:
                raise RuntimeError(f"stake() reverted: {tx_hash.hex()}")

            logger.info("StakingContract.stake(%.4f ETH) → tx=%s", amount_eth, tx_hash.hex()[:20])
            return tx_hash.hex()

        except Exception as exc:
            logger.error("stake failed: %s", exc)
            return ""

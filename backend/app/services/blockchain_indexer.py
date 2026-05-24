"""
blockchain_indexer.py — Custom Indexer (Mini The Graph in Python).

Runs as a background asyncio task started in main.py lifespan.
Polls the Hardhat / EVM node every POLL_INTERVAL seconds.
For each contract, fetches logs from (last_known_block + 1) to current_block,
dispatches events to handlers, then persists the new last_block.

Contract events indexed:
  IdentityRegistry   → AgentCreated, AgentVersionMinted, AgentStatusChanged
  EscrowManager      → PaymentDeposited, FundsReleased, ClientRefunded
  StakingContract    → Staked, Unstaked, Slashed
  ValidationRegistry → ValidationRequest, ValidationResponse, JudgesAssigned,
                       ProviderSlashed, JudgeSlashed, TaskExpired
  ReputationRegistry → NewFeedback, FeedbackRevoked

The indexer is the ONLY writer to the identity zone of the DB.
agent_service.py is the ONLY writer to the telemetry zone.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from app.core.config import get_settings
from app.db.agent_repo import get_last_block, set_last_block
from app.db.collaboration_repo import insert_collaboration_score
from app.db.escrow_repo import insert_escrow_event
from app.db.identity_repo import upsert_agent_identity, upsert_agent_version
from app.db.reputation_repo import insert_reputation_event, mark_revoked
from app.db.validation_repo import insert_validation_event

logger   = logging.getLogger(__name__)
settings = get_settings()

POLL_INTERVAL = 2       # seconds between block polls
BLOCK_CHUNK   = 500     # max blocks per get_logs call (avoids node timeouts)


# ── Minimal event ABIs ────────────────────────────────────────────────────────

_IDENTITY_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "name": "agentId",   "type": "string"},
            {"indexed": True,  "name": "tokenId",   "type": "uint256"},
            {"indexed": True,  "name": "owner",     "type": "address"},
            {"indexed": False, "name": "agentType", "type": "uint8"},
            {"indexed": False, "name": "agentURI",  "type": "string"},
            {"indexed": False, "name": "version",   "type": "string"},
        ],
        "name": "AgentCreated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "name": "agentId",         "type": "string"},
            {"indexed": True,  "name": "newTokenId",      "type": "uint256"},
            {"indexed": True,  "name": "previousTokenId", "type": "uint256"},
            {"indexed": False, "name": "agentURI",        "type": "string"},
            {"indexed": False, "name": "version",         "type": "string"},
        ],
        "name": "AgentVersionMinted",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agentId",   "type": "string"},
            {"indexed": False, "name": "oldStatus", "type": "uint8"},
            {"indexed": False, "name": "newStatus", "type": "uint8"},
        ],
        "name": "AgentStatusChanged",
        "type": "event",
    },
]

_ESCROW_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId", "type": "string"},
            {"indexed": True,  "name": "client", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
        ],
        "name": "PaymentDeposited",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId",           "type": "string"},
            {"indexed": True,  "name": "provider",         "type": "address"},
            {"indexed": False, "name": "providerAmount",   "type": "uint256"},
            {"indexed": False, "name": "totalJudgeAmount", "type": "uint256"},
        ],
        "name": "FundsReleased",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId", "type": "string"},
            {"indexed": True,  "name": "client", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
        ],
        "name": "ClientRefunded",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId",           "type": "string"},
            {"indexed": True,  "name": "client",           "type": "address"},
            {"indexed": False, "name": "amount",           "type": "uint256"},
            {"indexed": False, "name": "participantCount", "type": "uint256"},
        ],
        "name": "PipelinePaymentDeposited",
        "type": "event",
    },
]

_STAKING_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agent",  "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
        ],
        "name": "Staked",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agent",  "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
        ],
        "name": "Unstaked",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agent",  "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "reason", "type": "string"},
        ],
        "name": "Slashed",
        "type": "event",
    },
]

_VALIDATION_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "validatorAddress", "type": "address"},
            {"indexed": True,  "name": "agentId",          "type": "uint256"},
            {"indexed": False, "name": "requestURI",       "type": "string"},
            {"indexed": True,  "name": "requestHash",      "type": "bytes32"},
        ],
        "name": "ValidationRequest",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "validatorAddress", "type": "address"},
            {"indexed": True,  "name": "agentId",          "type": "uint256"},
            {"indexed": True,  "name": "requestHash",      "type": "bytes32"},
            {"indexed": False, "name": "response",         "type": "uint8"},
            {"indexed": False, "name": "responseURI",      "type": "string"},
            {"indexed": False, "name": "responseHash",     "type": "bytes32"},
            {"indexed": False, "name": "tag",              "type": "string"},
        ],
        "name": "ValidationResponse",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId",          "type": "string"},
            {"indexed": False, "name": "judge0",          "type": "string"},
            {"indexed": False, "name": "judge1",          "type": "string"},
            {"indexed": False, "name": "judge2",          "type": "string"},
            {"indexed": False, "name": "commitDeadline",  "type": "uint256"},
            {"indexed": False, "name": "revealDeadline",  "type": "uint256"},
        ],
        "name": "JudgesAssigned",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agentId", "type": "string"},
            {"indexed": True,  "name": "wallet",  "type": "address"},
            {"indexed": False, "name": "amount",  "type": "uint256"},
        ],
        "name": "ProviderSlashed",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agentId", "type": "string"},
            {"indexed": True,  "name": "wallet",  "type": "address"},
            {"indexed": False, "name": "amount",  "type": "uint256"},
            {"indexed": False, "name": "reason",  "type": "string"},
        ],
        "name": "JudgeSlashed",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "taskId", "type": "string"},
        ],
        "name": "TaskExpired",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "name": "agentId", "type": "string"},
            {"indexed": False, "name": "taskId",  "type": "string"},
            {"indexed": False, "name": "score",   "type": "uint8"},
            {"indexed": False, "name": "mode",    "type": "uint8"},
        ],
        "name": "ScoreRecorded",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "taskId",          "type": "string"},
            {"indexed": True,  "name": "judgeId",         "type": "string"},
            {"indexed": False, "name": "vote",            "type": "uint8"},
            {"indexed": False, "name": "taskCompletion",  "type": "uint8"},
            {"indexed": False, "name": "outputQuality",   "type": "uint8"},
            {"indexed": False, "name": "noFabrication",   "type": "uint8"},
            {"indexed": False, "name": "toolUsage",       "type": "uint8"},
        ],
        "name": "VoteRevealed",
        "type": "event",
    },
]

_REPUTATION_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True,  "name": "agentId",       "type": "uint256"},
            {"indexed": True,  "name": "clientAddress",  "type": "address"},
            {"indexed": False, "name": "feedbackIndex",  "type": "uint64"},
            {"indexed": False, "name": "value",          "type": "int128"},
            {"indexed": False, "name": "valueDecimals",  "type": "uint8"},
            {"indexed": True,  "name": "indexedTag1",    "type": "string"},
            {"indexed": False, "name": "tag1",           "type": "string"},
            {"indexed": False, "name": "tag2",           "type": "string"},
            {"indexed": False, "name": "endpoint",       "type": "string"},
            {"indexed": False, "name": "feedbackURI",    "type": "string"},
            {"indexed": False, "name": "feedbackHash",   "type": "bytes32"},
        ],
        "name": "NewFeedback",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId",       "type": "uint256"},
            {"indexed": True, "name": "clientAddress",  "type": "address"},
            {"indexed": True, "name": "feedbackIndex",  "type": "uint64"},
        ],
        "name": "FeedbackRevoked",
        "type": "event",
    },
]

# Status codes from IdentityRegistry.sol AgentStatus enum
_STATUS_MAP = {0: "active", 1: "suspended", 2: "revoked"}


# ── Indexer ───────────────────────────────────────────────────────────────────

class BlockchainIndexer:
    """
    Polls EVM node for new blocks and dispatches contract events to DB handlers.
    Safe to run when node is unavailable — silently retries each poll cycle.
    """

    def __init__(self) -> None:
        self._w3: Web3 | None = None
        self._eigentrust_pending: bool = False
        self._background_tasks: set = set()  # garde les références pour éviter le GC

    # ── Connection ────────────────────────────────────────────────────────────

    @property
    def w3(self) -> Web3:
        if self._w3 is None:
            w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 5}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            self._w3 = w3
        return self._w3

    def _is_available(self) -> bool:
        try:
            return self.w3.is_connected()
        except Exception:
            return False

    def _contract(self, address: str, abi: list) -> Any:
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=abi,
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("BlockchainIndexer started (poll every %ds)", POLL_INTERVAL)
        while True:
            try:
                if self._is_available():
                    await self._process_new_blocks()
                else:
                    logger.debug("Indexer: node not reachable, skipping cycle")
            except Exception as exc:
                logger.warning("Indexer cycle error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)

    async def _process_new_blocks(self) -> None:
        self._eigentrust_pending = False
        current_block = self.w3.eth.block_number

        # Detect chain reset: if chain is behind what DB remembers, Anvil was restarted without --state
        _CONTRACT_NAMES = (
            "identity_registry", "escrow_manager", "staking_contract",
            "validation_registry", "reputation_registry",
        )
        max_known_block = max(get_last_block(n) for n in _CONTRACT_NAMES)
        if current_block < max_known_block:
            logger.warning(
                "Chain reset detected: current_block=%d < last_known=%d — wiping DB and re-indexing",
                current_block, max_known_block,
            )
            self._reset_db()

        contracts = [
            ("identity_registry",   settings.identity_registry_address,    _IDENTITY_ABI,    self._handle_identity),
            ("escrow_manager",      settings.escrow_manager_address,        _ESCROW_ABI,      self._handle_escrow),
            ("staking_contract",    settings.staking_contract_address,      _STAKING_ABI,     self._handle_staking),
            ("validation_registry", settings.validation_registry_address,   _VALIDATION_ABI,  self._handle_validation),
            ("reputation_registry", settings.reputation_registry_address,   _REPUTATION_ABI,  self._handle_reputation),
        ]

        for name, address, abi, handler in contracts:
            if not address:
                continue
            try:
                await self._index_contract(name, address, abi, handler, current_block)
            except Exception as exc:
                logger.warning("Indexer[%s] error: %s", name, exc)

        # Déclencher la sync EigenTrust si un verdict ou feedback pertinent a été capté
        if self._eigentrust_pending:
            from app.services.eigentrust_sync import sync_eigentrust_onchain
            task = asyncio.create_task(sync_eigentrust_onchain())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            self._eigentrust_pending = False
            logger.debug("EigenTrust sync schedulé")

    async def _index_contract(
        self,
        name:          str,
        address:       str,
        abi:           list,
        handler,
        current_block: int,
    ) -> None:
        from_block = get_last_block(name) + 1
        if from_block > current_block:
            return  # nothing new

        contract = self._contract(address, abi)

        # Process in chunks to avoid node timeout on large ranges
        chunk_start = from_block
        while chunk_start <= current_block:
            chunk_end = min(chunk_start + BLOCK_CHUNK - 1, current_block)
            # Fetch all events for this contract in the block range
            for event_abi in abi:
                if event_abi.get("type") != "event":
                    continue
                event_name = event_abi["name"]
                try:
                    event_obj   = getattr(contract.events, event_name)()
                    event_logs  = event_obj.get_logs(
                        from_block=chunk_start, to_block=chunk_end
                    )
                    for log in event_logs:
                        try:
                            handler(event_name, log)
                        except Exception as e:
                            logger.warning(
                                "Indexer[%s] handler error for %s: %s",
                                name, event_name, e,
                            )
                except Exception as e:
                    logger.warning("Indexer[%s] get_logs(%s) error: %s",
                                   name, event_name, e)

            chunk_start = chunk_end + 1

        set_last_block(name, current_block)
        logger.debug("Indexer[%s] processed up to block %d", name, current_block)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _event_id(self, log: Any) -> str:
        return f"{log['transactionHash'].hex()}-{log['logIndex']}"

    # ── IdentityRegistry ──────────────────────────────────────────────────────

    def _handle_identity(self, event_name: str, log: Any) -> None:
        args  = log["args"]
        block = log["blockNumber"]
        tx    = log["transactionHash"].hex()

        if event_name == "AgentCreated":
            agent_id = args["agentId"]
            token_id = int(args["tokenId"])
            logger.info("Indexer → AgentCreated: agentId=%s tokenId=%d", agent_id, token_id)

            # Write canonical identity row
            upsert_agent_identity(
                agent_id=agent_id,
                registration_id=str(uuid.uuid4()),  # indexer-generated UUID
                owner_address=args["owner"],
                current_token_id=token_id,
                agent_uri=args["agentURI"],
                version=args["version"],
                agent_type=int(args["agentType"]),
                status="active",
                tx_hash=tx,
                block_number=block,
                registered_at=self._now(),
            )
            # Write version row (v1)
            upsert_agent_version(
                token_id=token_id,
                agent_id=agent_id,
                version=args["version"],
                agent_uri=args["agentURI"],
                block_number=block,
                minted_at=self._now(),
            )
            # Sync in-memory agent_service cache
            self._sync_agent_service_cache(agent_id)

        elif event_name == "AgentVersionMinted":
            agent_id     = args["agentId"]
            new_token_id = int(args["newTokenId"])
            new_version  = args["version"]
            logger.info("Indexer → AgentVersionMinted: agentId=%s newTokenId=%d version=%s",
                        agent_id, new_token_id, new_version)

            # Update current_token_id on identity row
            upsert_agent_identity(
                agent_id=agent_id,
                registration_id="",  # will not overwrite if empty handled by upsert
                owner_address="",
                current_token_id=new_token_id,
                agent_uri=args["agentURI"],
                version=new_version,
                tx_hash=tx,
                block_number=block,
            )
            # Add new version row
            upsert_agent_version(
                token_id=new_token_id,
                agent_id=agent_id,
                version=new_version,
                agent_uri=args["agentURI"],
                block_number=block,
                minted_at=self._now(),
            )
            self._sync_agent_service_cache(agent_id)

        elif event_name == "AgentStatusChanged":
            agent_id   = args["agentId"]
            new_status = _STATUS_MAP.get(args["newStatus"], "unknown")
            logger.info("Indexer → AgentStatusChanged: agentId=%s status=%s",
                        agent_id, new_status)
            from app.db.identity_repo import update_agent_status
            update_agent_status(agent_id, new_status)

    # ── EscrowManager ─────────────────────────────────────────────────────────

    def _handle_escrow(self, event_name: str, log: Any) -> None:
        args     = log["args"]
        block    = log["blockNumber"]
        tx       = log["transactionHash"].hex()
        event_id = self._event_id(log)

        if event_name == "PaymentDeposited":
            logger.info("Indexer → PaymentDeposited: task=%s", args["taskId"])
            insert_escrow_event(
                event_id=event_id,
                task_id=args["taskId"],
                event_type="deposited",
                client=args["client"],
                amount_wei=str(args["amount"]),
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "FundsReleased":
            logger.info("Indexer → FundsReleased: task=%s provider=%s",
                        args["taskId"], args["provider"][:10])
            insert_escrow_event(
                event_id=event_id,
                task_id=args["taskId"],
                event_type="released",
                provider=args["provider"],
                amount_wei=str(args["providerAmount"]),
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "ClientRefunded":
            logger.info("Indexer → ClientRefunded: task=%s", args["taskId"])
            insert_escrow_event(
                event_id=event_id,
                task_id=args["taskId"],
                event_type="refunded",
                client=args["client"],
                amount_wei=str(args["amount"]),
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "PipelinePaymentDeposited":
            logger.info(
                "Indexer → PipelinePaymentDeposited: task=%s client=%s amount=%s participants=%d",
                args["taskId"], args["client"][:10], args["amount"], args["participantCount"],
            )
            insert_escrow_event(
                event_id=event_id,
                task_id=args["taskId"],
                event_type="pipeline_deposited",
                client=args["client"],
                amount_wei=str(args["amount"]),
                tx_hash=tx,
                block_number=block,
            )

    # ── StakingContract ───────────────────────────────────────────────────────

    def _handle_staking(self, event_name: str, log: Any) -> None:
        args     = log["args"]
        block    = log["blockNumber"]
        tx       = log["transactionHash"].hex()
        event_id = self._event_id(log)

        from app.db.database import StakingEvent, get_session
        now = self._now()
        with get_session() as s:
            if s.get(StakingEvent, event_id):
                return
            s.add(StakingEvent(
                id=event_id,
                event_type=event_name.lower(),   # "staked" | "unstaked" | "slashed"
                agent_wallet=args["agent"],
                amount_wei=str(args["amount"]),
                reason=args.get("reason"),
                tx_hash=tx,
                block_number=block,
                created_at=now,
            ))
            s.commit()
        logger.info("Indexer → %s: wallet=%s", event_name, args["agent"][:10])

    # ── ValidationRegistry ────────────────────────────────────────────────────

    def _handle_validation(self, event_name: str, log: Any) -> None:
        args     = log["args"]
        block    = log["blockNumber"]
        tx       = log["transactionHash"].hex()
        event_id = self._event_id(log)

        if event_name == "ValidationRequest":
            task_hash = args["requestHash"].hex()
            insert_validation_event(
                event_id=event_id,
                task_id=task_hash,
                event_type="request",
                agent_id=str(args["agentId"]),   # tokenId used as agentId in ERC-8004
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "ValidationResponse":
            task_hash  = args["requestHash"].hex()
            response = args["response"]   # uint8: 100 VALID, 50 DISPUTED, 0 INVALID
            if response == 100:
                verdict = "VALID"
            elif response == 50:
                verdict = "DISPUTED"
            else:
                verdict = "INVALID"
            score      = float(response)
            agent_id   = str(args["agentId"])
            logger.info("Indexer → ValidationResponse: agentId=%s verdict=%s score=%s",
                        agent_id, verdict, score)
            insert_validation_event(
                event_id=event_id,
                task_id=task_hash,
                event_type="verdict",
                agent_id=agent_id,
                verdict=verdict,
                score=score,
                tx_hash=tx,
                block_number=block,
            )
            self._apply_verdict_to_telemetry(agent_id, verdict, score)
            # Nouveau verdict juge → recalculer EigenTrust (signal Judge→Agent)
            self._eigentrust_pending = True

        elif event_name == "JudgesAssigned":
            insert_validation_event(
                event_id=event_id,
                task_id=args["taskId"],
                event_type="judges_assigned",
                tx_hash=tx,
                block_number=block,
            )

        elif event_name in ("ProviderSlashed", "JudgeSlashed"):
            insert_validation_event(
                event_id=event_id,
                task_id=f"slash-{event_id}",
                event_type=event_name.lower(),
                agent_id=args["agentId"],
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "TaskExpired":
            insert_validation_event(
                event_id=event_id,
                task_id=args["taskId"],
                event_type="expired",
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "VoteRevealed":
            task_id  = args["taskId"]
            judge_id = args["judgeId"]
            vote     = int(args["vote"])   # 0=NONE, 1=VALID, 2=INVALID
            verdict  = "VALID" if vote == 1 else "INVALID" if vote == 2 else "ABSTAIN"
            score    = float(
                args["taskCompletion"] + args["outputQuality"] +
                args["noFabrication"] + args["toolUsage"]
            ) / 4.0
            logger.info(
                "Indexer → VoteRevealed: taskId=%s judgeId=%s verdict=%s score=%.1f",
                task_id, judge_id, verdict, score,
            )
            insert_validation_event(
                event_id=event_id,
                task_id=task_id,
                event_type="vote_revealed",
                judge_id=judge_id,
                verdict=verdict,
                score=score,
                tx_hash=tx,
                block_number=block,
            )

        elif event_name == "ScoreRecorded":
            agent_id = args["agentId"]
            score    = float(args["score"])
            mode     = int(args["mode"])
            logger.info(
                "Indexer → ScoreRecorded: agentId=%s score=%.0f mode=%d",
                agent_id, score, mode,
            )
            insert_collaboration_score(
                event_id=event_id,
                agent_id=agent_id,
                task_id=args["taskId"],
                score=score,
                mode=mode,
                tx_hash=tx,
                block_number=block,
            )
            self._eigentrust_pending = True

    # ── Chain reset ───────────────────────────────────────────────────────────

    def _reset_db(self) -> None:
        """
        Wipe all on-chain-derived tables and reset last_block counters to 0.
        Called when a chain reset is detected (Anvil restarted without --state).
        Telemetry (agent_service usage stats) is intentionally preserved.
        """
        from app.db.database import (
            Agent, AgentVersion, CollaborationLog, ReputationEvent,
            get_session,
        )
        from app.db.agent_repo import set_last_block

        with get_session() as s:
            s.query(CollaborationLog).delete()
            s.query(ReputationEvent).delete()
            s.query(AgentVersion).delete()
            s.query(Agent).delete()
            s.commit()

        for name in (
            "identity_registry", "escrow_manager",
            "staking_contract", "validation_registry", "reputation_registry",
        ):
            set_last_block(name, 0)

        # Clear in-memory agent cache so stale records are gone
        from app.services import agent_service as svc
        svc._records.clear()
        svc._agent_index.clear()

        logger.warning("DB reset complete — all on-chain tables cleared, re-indexing from block 0")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sync_agent_service_cache(self, agent_id: str) -> None:
        """
        Called by the indexer after writing a canonical AgentCreated row to DB.

        Two cases:
          - Agent not yet in _records (new registration via pure flow) → CREATE record
          - Agent already in _records (restart / legacy) → UPDATE fields
        """
        try:
            import json
            from datetime import datetime, timezone

            from app.db.identity_repo import get_agent_identity
            from app.db.telemetry_repo import get_telemetry
            from app.services import agent_service as svc
            from app.services.ngrok_service import register_agent_endpoint

            row = get_agent_identity(agent_id)
            if not row:
                return

            tel      = get_telemetry(agent_id) or {}
            reg_file = None
            if row.get("identity_metadata"):
                try:
                    reg_file = svc.AgentRegistrationFile(**json.loads(row["identity_metadata"]))
                except Exception:
                    pass

            # Merge telemetry into capabilities for display
            if reg_file and tel:
                caps = dict(reg_file.capabilities)
                caps.update({
                    "tasks_performed":      tel.get("tasks_performed", 0),
                    "usage_count":          tel.get("usage_count", 0),
                    "avg_response_time":    tel.get("avg_response_time", 0),
                    "task_completion_rate": tel.get("task_completion_rate", 0),
                    "uptime":               tel.get("uptime", 99.9),
                    "monthly_tasks":        tel.get("monthly_tasks", [0]*12),
                    "weekly_success":       tel.get("weekly_success", [0]*7),
                    "success_rate":         tel.get("success_rate", 0),
                    "reputation_score":     tel.get("reputation_score", 0),
                })
                reg_file = reg_file.model_copy(update={"capabilities": caps})

            pricing  = reg_file.pricing if reg_file else {}
            endpoint = register_agent_endpoint(agent_id)
            now      = datetime.now(timezone.utc)

            if agent_id in svc._agent_index:
                # UPDATE existing record
                rid    = svc._agent_index[agent_id]
                record = svc._records[rid]
                svc._records[rid] = record.model_copy(update={
                    "current_token_id":  row["current_token_id"],
                    "tx_hash":           row["tx_hash"],
                    "agent_uri":         row["agent_uri"] or record.agent_uri,
                    "ipfs_cid":          row["ipfs_cid"]  or record.ipfs_cid,
                    "version":           row["version"]   or record.version,
                    "status":            svc.AgentStatus(row["status"]),
                    "registration_file": reg_file or record.registration_file,
                    "updated_at":        now,
                    "versions": [svc.AgentVersionInfo(
                        token_id=row["current_token_id"] or 0,
                        version=row["version"] or record.version,
                        agent_uri=row["agent_uri"] or "",
                        docker_image=row["docker_image"],
                        minted_at=now,
                    )] if row["current_token_id"] else record.versions,
                })
                logger.info("Cache updated: %s tokenId=%s", agent_id, row["current_token_id"])
            else:
                # CREATE new record — this is the moment the agent becomes visible in the API
                rid = row["registration_id"]
                record = svc.AgentRecord(
                    id=rid,
                    agent_id=agent_id,
                    current_token_id=row["current_token_id"],
                    agent_registry=f"eip155:{settings.chain_id}:{settings.identity_registry_address}",
                    name=row.get("name") or agent_id,
                    version=row.get("version") or "1.0.0",
                    agent_type=svc.AgentType.JUDGE if row.get("agent_type") == 1 else svc.AgentType.PROVIDER,
                    status=svc.AgentStatus(row["status"]),
                    owner_address=row["owner_address"],
                    ipfs_cid=row["ipfs_cid"],
                    agent_uri=row["agent_uri"],
                    metadata_hash=None,
                    docker_image=row["docker_image"],
                    platform_endpoint=endpoint,
                    stake_amount=row.get("stake_amount") or 0.0,
                    price_per_task=row.get("price_per_task") or pricing.get("price_per_task", 0.0),
                    access_duration_days=pricing.get("access_duration_days", 30),
                    max_calls_per_day=pricing.get("max_calls_per_day", 100),
                    tx_hash=row["tx_hash"],
                    registered_at=datetime.fromisoformat(row["registered_at"]) if row.get("registered_at") else now,
                    updated_at=now,
                    versions=[svc.AgentVersionInfo(
                        token_id=row["current_token_id"] or 0,
                        version=row.get("version") or "1.0.0",
                        agent_uri=row["agent_uri"] or "",
                        docker_image=row["docker_image"],
                        minted_at=now,
                    )] if row["current_token_id"] else [],
                    registration_file=reg_file,
                )
                svc._records[rid]          = record
                svc._agent_index[agent_id] = rid
                logger.info("Cache CREATED: %s tokenId=%s status=%s",
                            agent_id, row["current_token_id"], row["status"])

        except Exception as e:
            logger.warning("_sync_agent_service_cache failed: %s", e)

    # ── ReputationRegistry ────────────────────────────────────────────────────

    def _update_reputation_from_eigentrust(self, agent_token_id: int, score_100: float) -> None:
        """
        Called when NewFeedback(tag1='eigenTrust') is indexed.
        Writes the EigenTrust final_score (converted to 0-100) into agent_telemetry
        so the UX always displays the canonical EigenTrust reputation.
        """
        try:
            from app.db.database import Agent, get_session
            from app.db.telemetry_repo import upsert_telemetry
            from app.services import agent_service as svc

            with get_session() as s:
                row = s.query(Agent).filter(Agent.current_token_id == agent_token_id).first()
                if not row:
                    return
                agent_id = row.agent_id

            upsert_telemetry(agent_id, reputation_score=score_100)
            svc._refresh_record_telemetry(agent_id, {"reputation_score": score_100})
            logger.info(
                "Reputation updated from EigenTrust: agent=%s tokenId=%d score=%.1f/100",
                agent_id, agent_token_id, score_100,
            )
        except Exception as e:
            logger.warning("_update_reputation_from_eigentrust failed: %s", e)

    def _handle_reputation(self, event_name: str, log: Any) -> None:
        args     = log["args"]
        block    = log["blockNumber"]
        tx       = log["transactionHash"].hex()
        event_id = self._event_id(log)

        if event_name == "NewFeedback":
            agent_token_id = int(args["agentId"])
            client_address = args["clientAddress"]
            feedback_index = int(args["feedbackIndex"])
            value          = int(args["value"])
            value_decimals = int(args["valueDecimals"])
            tag1           = args["tag1"]
            tag2           = args.get("tag2", "")
            endpoint       = args.get("endpoint", "")
            feedback_uri   = args.get("feedbackURI", "")
            feedback_hash  = args["feedbackHash"].hex() if args.get("feedbackHash") else ""

            logger.info(
                "Indexer → NewFeedback: tokenId=%d tag1=%s value=%d client=%s",
                agent_token_id, tag1, value, client_address[:10],
            )
            insert_reputation_event(
                event_id=event_id,
                event_type="new_feedback",
                agent_token_id=agent_token_id,
                client_address=client_address,
                feedback_index=feedback_index,
                value=value,
                value_decimals=value_decimals,
                tag1=tag1,
                tag2=tag2,
                endpoint=endpoint,
                feedback_uri=feedback_uri,
                feedback_hash=feedback_hash,
                is_revoked=0,
                tx_hash=tx,
                block_number=block,
            )
            # Seul "successRate" (signal juge technique) déclenche un recalcul EigenTrust.
            # "starred" (note utilisateur) est uniquement le facteur f[i] — pas un déclencheur.
            # "eigenTrust" est écrit par nous — pas de boucle infinie.
            if tag1 == "successRate":
                self._eigentrust_pending = True
            elif tag1 == "eigenTrust":
                # EigenTrust score finalisé → mettre à jour agent_telemetry.reputation_score
                # value=finalScore×1000, valueDecimals=3  →  finalScore ∈ [0,1]  →  ×100 pour UI
                dec = value_decimals or 0
                et_final = value / (10 ** dec) if dec else float(value)
                et_score_100 = round(et_final * 100, 1)
                self._update_reputation_from_eigentrust(agent_token_id, et_score_100)
            # "starred" et autres tags → ignorés ici (f[i] calculé dans eigentrust_service)

        elif event_name == "FeedbackRevoked":
            agent_token_id = int(args["agentId"])
            client_address = args["clientAddress"]
            feedback_index = int(args["feedbackIndex"])
            logger.info(
                "Indexer → FeedbackRevoked: tokenId=%d index=%d client=%s",
                agent_token_id, feedback_index, client_address[:10],
            )
            insert_reputation_event(
                event_id=event_id,
                event_type="revoked",
                agent_token_id=agent_token_id,
                client_address=client_address,
                feedback_index=feedback_index,
                tx_hash=tx,
                block_number=block,
            )
            mark_revoked(agent_token_id, client_address, feedback_index)

    def _apply_verdict_to_telemetry(self, agent_id: str, verdict: str, score: float) -> None:
        """
        ValidationResponse → update telemetry (success_rate, reputation_score).
        Writes to agent_telemetry only (telemetry zone).
        Will be replaced by ReputationContract events in the future.
        """
        try:
            from app.services import agent_service as svc
            svc_instance = svc.AgentService.__new__(svc.AgentService)
            svc_instance.update_validation_metrics(agent_id, verdict=verdict, score=score)
        except Exception as e:
            logger.debug("_apply_verdict_to_telemetry failed (non-critical): %s", e)

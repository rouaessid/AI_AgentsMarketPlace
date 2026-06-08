from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any

from app.repo.database import get_session
from app.entities.access import AccessGrant, ValidationSession


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Access Grants ─────────────────────────────────────────────────────────────

def create_access_grant(agent_id: str, task_id: str) -> str:
    grant_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(AccessGrant(
            id=grant_id, agent_id=agent_id,
            task_id=task_id, status="granted", granted_at=_now(),
        ))
        s.commit()
    return grant_id


def get_access_grant_by_task(task_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.query(AccessGrant).filter(AccessGrant.task_id == task_id).first()
        if not row:
            return None
        return {c.name: getattr(row, c.name) for c in AccessGrant.__table__.columns}


def _get_onchain_contract():
    from app.core.config import get_settings
    from web3 import Web3
    settings = get_settings()
    if not settings.escrow_manager_address or not settings.rpc_url:
        return None, None
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 5}))
    abi = [{"inputs": [{"type": "string", "name": ""}], "name": "taskClients",
            "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"}]
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.escrow_manager_address), abi=abi
    )
    return w3, contract


def get_access_grant(agent_id: str, buyer_wallet: str) -> dict[str, Any] | None:
    """
    Retourne le grant DB si le buyer a payé on-chain pour cet agent.
    Source de vérité : EscrowManager.taskClients[task_id] == buyer_wallet.
    """
    with get_session() as s:
        grants = s.query(AccessGrant).filter(
            AccessGrant.agent_id == agent_id,
            AccessGrant.status == "granted",
        ).all()

    if not grants:
        return None

    try:
        _, contract = _get_onchain_contract()
        if not contract:
            return None
        for grant in grants:
            onchain_buyer = contract.functions.taskClients(grant.task_id).call()
            if onchain_buyer.lower() == buyer_wallet.lower():
                return {c.name: getattr(grant, c.name) for c in AccessGrant.__table__.columns}
    except Exception:
        pass
    return None


def verify_access(agent_id: str, buyer_wallet: str) -> bool:
    """
    Vérifie l'accès en consultant EscrowManager.taskClients on-chain.
    buyer_wallet n'est pas stocké en DB — vérité depuis le contrat.
    """
    return get_access_grant(agent_id, buyer_wallet) is not None


# ── Validation Sessions ───────────────────────────────────────────────────────

def upsert_validation_session(
    agent_id:   str,
    val_task_id: str | None = None,
    started_at:  str | None = None,
) -> None:
    with get_session() as s:
        row = s.get(ValidationSession, agent_id)
        if row:
            row.val_task_id = val_task_id
            if started_at is not None:
                row.started_at = started_at
        else:
            s.add(ValidationSession(
                agent_id=agent_id,
                val_task_id=val_task_id,
                started_at=started_at,
            ))
        s.commit()


def get_validation_session(agent_id: str) -> dict[str, Any] | None:
    with get_session() as s:
        row = s.get(ValidationSession, agent_id)
        if not row:
            return None
        return {c.name: getattr(row, c.name) for c in ValidationSession.__table__.columns}


def clear_validation_session(agent_id: str) -> None:
    """Supprime la session de validation (tâche terminée ou expirée)."""
    with get_session() as s:
        row = s.get(ValidationSession, agent_id)
        if row:
            s.delete(row)
            s.commit()


def get_verdicts_by_judge(judge_id: str) -> list[dict]:
    """
    Fetches VoteRevealed events for judge_id from ValidationRegistry (on-chain).
    Returns list of dicts: {agent_id, verdict, score, justification, created_at}.
    """
    import logging
    from datetime import datetime, timezone
    _log = logging.getLogger(__name__)
    try:
        from web3 import Web3
        from eth_abi import decode as abi_decode
        from app.core.config import get_settings
        settings = get_settings()
        if not settings.validation_registry_address or not settings.rpc_url:
            return []

        w3   = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 10}))
        addr = Web3.to_checksum_address(settings.validation_registry_address)

        latest     = w3.eth.block_number
        from_block = max(0, latest - 10_000)

        def _get_logs_in_chunks(filter_params: dict, start_block: int, end_block: int) -> list:
            batch_logs = []
            max_span = 2000
            cursor = start_block
            while cursor <= end_block:
                chunk_end = min(cursor + max_span - 1, end_block)
                try:
                    batch_logs.extend(w3.eth.get_logs({**filter_params, "fromBlock": cursor, "toBlock": chunk_end}))
                except Exception as exc:
                    _log.warning("get_logs chunk %s-%s failed: %s", cursor, chunk_end, exc)
                    raise
                cursor = chunk_end + 1
            return batch_logs

        # VoteRevealed(string indexed taskId, string indexed judgeId,
        #              uint8 vote, uint8 taskCompletion, uint8 outputQuality,
        #              uint8 noFabrication, uint8 toolUsage)
        vote_sig    = "0x" + w3.keccak(text="VoteRevealed(string,string,uint8,uint8,uint8,uint8,uint8)").hex()
        judge_topic = "0x" + w3.keccak(text=judge_id).hex()

        vote_logs = _get_logs_in_chunks({
            "address": addr,
            "topics":  [vote_sig, None, judge_topic],
        }, from_block, latest)
        if not vote_logs:
            return []

        # Parse vote data and collect taskId hashes
        vote_by_task: dict[str, dict] = {}
        for log in vote_logs:
            task_hash = log["topics"][1].hex()
            vote_int, tc, oq, nf, tu = abi_decode(
                ["uint8", "uint8", "uint8", "uint8", "uint8"], bytes(log["data"])
            )
            vote_by_task[task_hash] = {
                "vote":         "VALID" if vote_int == 1 else "INVALID",
                "score":        int(tc) + int(oq) + int(nf) + int(tu),
                "block_number": log["blockNumber"],
            }

        # ScoreRecorded(string agentId, string taskId, uint8 score, uint8 mode)
        # — all non-indexed, lets us recover agentId per taskId
        score_sig  = "0x" + w3.keccak(text="ScoreRecorded(string,string,uint8,uint8)").hex()
        score_logs = _get_logs_in_chunks({
            "address": addr,
            "topics":  [score_sig],
        }, from_block, latest)
        task_agent_map: dict[str, str] = {}
        for log in score_logs:
            try:
                agent_str, task_str, _, _ = abi_decode(
                    ["string", "string", "uint8", "uint8"], bytes(log["data"])
                )
                task_hash = w3.keccak(text=task_str).hex()
                task_agent_map[task_hash] = agent_str
            except Exception:
                pass

        results = []
        for task_hash, vote_data in vote_by_task.items():
            agent_id_val = task_agent_map.get(task_hash, "unknown")
            ts: str | None = None
            try:
                block = w3.eth.get_block(vote_data["block_number"])
                ts = datetime.fromtimestamp(int(block["timestamp"]), tz=timezone.utc).isoformat()
            except Exception:
                pass
            results.append({
                "agent_id":      agent_id_val,
                "verdict":       vote_data["vote"],
                "score":         vote_data["score"],
                "justification": f"On-chain verdict: {vote_data['vote']}",
                "created_at":    ts,
            })

        return sorted(results, key=lambda x: x.get("created_at") or "", reverse=True)

    except Exception as exc:
        _log.warning("get_verdicts_by_judge(%s) failed: %s", judge_id, exc)
        return []



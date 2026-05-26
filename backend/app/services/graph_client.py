"""
graph_client.py — HTTP client for The Graph subgraph (agentmarket).

Replaces blockchain_indexer.py for read-only blockchain data.
All queries hit the GraphQL endpoint; no direct Web3 / RPC calls here.
"""
from __future__ import annotations
import logging
from typing import Any

import httpx
from web3 import Web3

from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


def _gql(query: str, variables: dict | None = None) -> dict[str, Any]:
    """Execute a GraphQL query against The Graph and return data dict."""
    url = settings.graph_url
    if not url:
        logger.warning("graph_url not configured — returning empty result")
        return {}
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        r = httpx.post(url, json=payload, timeout=4)
        r.raise_for_status()
        body = r.json()
        if "errors" in body:
            logger.warning("GraphQL errors: %s", body["errors"])
            return {}
        return body.get("data") or {}
    except Exception as exc:
        logger.warning("The Graph query failed: %s", exc)
        return {}


# ── Agent identity ─────────────────────────────────────────────────────────────

def get_all_agents(first: int = 200) -> list[dict]:
    """
    Return all Agent entities from The Graph (paginated by `first`).
    Used at startup to bootstrap agent_embeddings table when DB is empty.
    """
    data = _gql("""
        query GetAllAgents($first: Int!) {
            agents(first: $first, orderBy: tokenId, orderDirection: asc) {
                id
                tokenId
                owner
                agentType
                agentURI
                version
                status
            }
        }
    """, {"first": first})
    return data.get("agents") or []


def get_agent(agent_id: str) -> dict | None:
    """
    Return Agent entity from The Graph, or None if not yet indexed.
    Fields: id (agentId str), tokenId, owner, agentType, agentURI, version, status
    """
    data = _gql("""
        query GetAgent($id: String!) {
            agent(id: $id) {
                id
                tokenId
                owner
                agentType
                agentURI
                version
                status
            }
        }
    """, {"id": agent_id})
    return data.get("agent")


def get_agent_score(agent_id: str) -> dict | None:
    """Return AgentScore entity (averageScore 0-100, totalTasks)."""
    data = _gql("""
        query GetAgentScore($id: String!) {
            agentScore(id: $id) {
                id
                averageScore
                totalTasks
            }
        }
    """, {"id": agent_id})
    return data.get("agentScore")


# ── Escrow ─────────────────────────────────────────────────────────────────────

def get_escrow_events_for_task(task_id: str) -> list[dict]:
    """
    Return EscrowEvents for a taskId string.
    The Graph stores taskId as keccak256(taskId_string) since it's an indexed param.
    """
    task_id_hash = Web3.keccak(text=task_id).hex()
    data = _gql("""
        query GetEscrowEvents($taskId: Bytes!) {
            escrowEvents(where: {taskId: $taskId}, orderBy: blockNumber) {
                id
                taskId
                eventType
                participant
                amount
                providerAmount
                blockNumber
                blockTimestamp
                transactionHash
            }
        }
    """, {"taskId": task_id_hash})
    return data.get("escrowEvents") or []


def payment_deposited_for_task(task_id: str) -> bool:
    """Return True if a PaymentDeposited event exists for this taskId."""
    events = get_escrow_events_for_task(task_id)
    return any(e.get("eventType") == "PaymentDeposited" for e in events)


# ── Judge reputation ───────────────────────────────────────────────────────────

def get_judge_score(judge_wallet: str) -> dict | None:
    """
    Return JudgeScore entity from The Graph.
    Fields: id (wallet), agreementRate (0-100), totalVotes
    judge_wallet must be a 0x hex address — non-hex strings are ignored.
    """
    wallet = judge_wallet.lower()
    if not wallet.startswith("0x") or len(wallet) != 42:
        return None
    data = _gql("""
        query GetJudgeScore($id: Bytes!) {
            judgeScore(id: $id) {
                id
                agreementRate
                totalVotes
            }
        }
    """, {"id": wallet})
    return data.get("judgeScore")


def get_judge_reputation(judge_id: str) -> dict:
    """
    Return judge agreement stats from The Graph JudgeScore entity.
    Falls back to neutral 0.5 if not indexed yet.
    judge_id may be a wallet address (0x...) or agent_id string.
    """
    score = get_judge_score(judge_id)
    if score:
        rate = int(score.get("agreementRate", 50)) / 100.0
        total = int(score.get("totalVotes", 0))
        return {
            "judge_id":          judge_id,
            "total_validations": total,
            "agreement_count":   round(rate * total),
            "agreement_rate":    rate,
        }
    return {
        "judge_id":          judge_id,
        "total_validations": 0,
        "agreement_count":   0,
        "agreement_rate":    0.5,
    }


# ── Reputation signals ─────────────────────────────────────────────────────────

def get_reputation_events(agent_token_id: int) -> list[dict]:
    """Return ReputationEvents from The Graph for a given token ID."""
    data = _gql("""
        query GetReputation($agentId: BigInt!) {
            reputationEvents(
                where: {agentId: $agentId}
                orderBy: blockNumber
                orderDirection: asc
            ) {
                id
                agentId
                clientAddress
                feedbackIndex
                value
                valueDecimals
                tag1
                tag2
                endpoint
                feedbackURI
                blockNumber
                blockTimestamp
                transactionHash
            }
        }
    """, {"agentId": str(agent_token_id)})
    return data.get("reputationEvents") or []


def get_aggregated_reputation(agent_token_id: int) -> dict:
    """Compute aggregated reputation per tag1 from The Graph ReputationEvents."""
    events = get_reputation_events(agent_token_id)
    per_tag: dict[str, dict] = {}
    for ev in events:
        tag = ev.get("tag1") or "unknown"
        if tag not in per_tag:
            per_tag[tag] = {"count": 0, "sum": 0}
        per_tag[tag]["count"] += 1
        decimals = int(ev.get("valueDecimals") or 0)
        raw = int(ev.get("value") or 0)
        normalised = raw / (10 ** decimals) if decimals else raw
        per_tag[tag]["sum"] += normalised
    return {
        tag: {
            "count":   d["count"],
            "sum":     d["sum"],
            "average": round(d["sum"] / d["count"], 4) if d["count"] else 0,
        }
        for tag, d in per_tag.items()
    }


# ── Validation scores (replaces collaboration_log) ────────────────────────────

def get_validation_scores_for_agent(agent_id: str, mode: int | None = None) -> list[int]:
    """
    Return validation scores for an agent from The Graph ValidationEvent entities.
    mode=0 → solo, mode=1 → pipeline, None → all.
    """
    where = {"agentId": agent_id}
    if mode is not None:
        where["mode"] = mode
    data = _gql("""
        query GetValScores($where: ValidationEvent_filter!) {
            validationEvents(where: $where, orderBy: blockNumber, orderDirection: asc) {
                score
                mode
            }
        }
    """, {"where": where})
    return [int(e["score"]) for e in (data.get("validationEvents") or [])]


def get_solo_scores(agent_id: str) -> list[int]:
    return get_validation_scores_for_agent(agent_id, mode=0)


def get_pipeline_scores(agent_id: str) -> list[int]:
    return get_validation_scores_for_agent(agent_id, mode=1)


def get_latest_eigentrust_score(agent_token_id: int | None) -> float | None:
    """Return latest EigenTrust score (0-100) from The Graph, or None."""
    if not agent_token_id:
        return None
    events = get_reputation_events(agent_token_id)
    eigen = [e for e in events if e.get("tag1") == "eigenTrust"]
    if not eigen:
        return None
    latest = eigen[-1]
    decimals = int(latest.get("valueDecimals") or 0)
    raw = int(latest.get("value") or 0)
    normalised = raw / (10 ** decimals) if decimals else float(raw)
    return round(normalised * 100, 1)

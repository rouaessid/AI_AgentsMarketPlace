"""
graph_client.py — blockchain data client for AgentMarket.

Règle architecturale :
  The Graph  → données itérables / historiques (agents list, starred feedback, audit)
  RPC direct → état courant d'une entité connue (scores, eigenTrust, judgeRate)
"""
from __future__ import annotations
import logging
import time
from typing import Any

import httpx
from web3 import Web3

from app.core.config import get_settings
from app.core.abis import (
    VALIDATION_REGISTRY_ABI  as _VALIDATION_ABI,
    REPUTATION_REGISTRY_ABI  as _REPUTATION_ABI,
    IDENTITY_REGISTRY_ABI    as _IDENTITY_REGISTRY_ABI,
)

logger   = logging.getLogger(__name__)
settings = get_settings()

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL = 30.0


def _gql(query: str, variables: dict | None = None) -> dict[str, Any]:
    """Execute a GraphQL query against The Graph and return data dict (cached 30s)."""
    url = settings.graph_url
    if not url:
        logger.warning("graph_url not configured — returning empty result")
        return {}
    cache_key = query + str(variables)
    now = time.monotonic()
    if cache_key in _CACHE:
        ts, cached = _CACHE[cache_key]
        if now - ts < _TTL:
            return cached
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
        data = body.get("data") or {}
        _CACHE[cache_key] = (now, data)
        return data
    except Exception as exc:
        logger.warning("The Graph query failed: %s", exc)
        return {}


# ── Agent identity — The Graph (liste non-itérable en direct) ─────────────────

def get_all_agents(first: int = 200) -> list[dict]:
    """Return all Agent entities from The Graph (paginated)."""
    data = _gql("""
        query GetAllAgents($first: Int!) {
            agents(first: $first, orderBy: tokenId, orderDirection: asc) {
                id tokenId owner agentType agentURI version status
            }
        }
    """, {"first": first})
    return data.get("agents") or []


def get_agent(agent_id: str) -> dict | None:
    """Return Agent entity from The Graph — tokenId, owner, metadata."""
    data = _gql("""
        query GetAgent($id: String!) {
            agent(id: $id) { id tokenId owner agentType agentURI version status }
        }
    """, {"id": agent_id})
    return data.get("agent")


# ── Agent score — direct RPC (state variable) ─────────────────────────────────

def get_agent_score(agent_id: str) -> dict | None:
    """Return agent validation score via direct RPC from ValidationRegistry."""
    rpc  = settings.rpc_url
    addr = settings.validation_registry_address
    if not rpc or not addr:
        return None
    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 4}))
        c  = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_VALIDATION_ABI)
        avg, total = c.functions.getAgentScore(agent_id).call()
        return {"id": agent_id, "averageScore": avg, "totalTasks": total}
    except Exception as exc:
        logger.warning("get_agent_score RPC failed for %s: %s", agent_id, exc)
        return None


# ── Validation history — The Graph (monthly + weekly breakdown) ───────────────

def get_agent_validation_history(agent_id: str) -> dict:
    """
    Query ValidationEvent entities for an agent from The Graph.
    Returns:
      monthly_tasks  : list[12] — task count per month (current year, Jan=index 0)
      weekly_success : list[7]  — avg score per weekday (Mon=0 … Sun=6)
    Returns zeros if The Graph is unavailable.
    """
    from datetime import datetime, timezone
    data = _gql("""
        query GetAgentHistory($agentId: String!) {
            validationEvents(
                where: { agentId: $agentId }
                orderBy: blockTimestamp
                orderDirection: asc
                first: 1000
            ) {
                score
                blockTimestamp
            }
        }
    """, {"agentId": agent_id})

    events = data.get("validationEvents") or []
    if not events:
        return {"monthly_tasks": [0]*12, "weekly_success": [0.0]*7}

    current_year   = datetime.now(timezone.utc).year
    monthly_tasks  = [0] * 12
    weekly_sums    = [0.0] * 7
    weekly_counts  = [0]   * 7

    for ev in events:
        ts    = int(ev["blockTimestamp"])
        score = int(ev["score"])
        dt    = datetime.fromtimestamp(ts, tz=timezone.utc)

        if dt.year == current_year:
            monthly_tasks[dt.month - 1] += 1

        dow = dt.weekday()          # 0=Mon … 6=Sun
        weekly_sums[dow]   += score
        weekly_counts[dow] += 1

    weekly_success = [
        round(weekly_sums[i] / weekly_counts[i], 1) if weekly_counts[i] > 0 else 0.0
        for i in range(7)
    ]

    return {"monthly_tasks": monthly_tasks, "weekly_success": weekly_success}


# ── Judge agreement rate — direct RPC (state variable) ────────────────────────

def _resolve_judge_wallet(judge_id: str) -> str | None:
    """Resolve a judge agent ID to its on-chain wallet address via IdentityRegistry."""
    if judge_id.startswith("0x") and len(judge_id) == 42:
        return judge_id

    identity_addr = settings.identity_registry_address
    rpc = settings.rpc_url
    if not rpc or not identity_addr:
        return None

    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 4}))
        identity = w3.eth.contract(address=Web3.to_checksum_address(identity_addr), abi=_IDENTITY_REGISTRY_ABI)
        wallet = identity.functions.getAgentWallet(judge_id).call()
        if isinstance(wallet, str) and wallet.startswith("0x") and len(wallet) == 42:
            return wallet
    except Exception as exc:
        logger.warning("Could not resolve judge wallet for %s: %s", judge_id, exc)
    return None


def get_judge_agreement_rate(judge_wallet: str) -> dict:
    """
    Return judge agreement rate via direct RPC — ValidationRegistry.getJudgeAgreementRate().
    Accepts either a judge wallet address or an agent ID.
    Falls back to neutral 0.5 if RPC unavailable.
    """
    rpc  = settings.rpc_url
    addr = settings.validation_registry_address
    if not rpc or not addr:
        return {
            "judge_id":          judge_wallet,
            "total_validations": 0,
            "agreement_count":   0,
            "agreement_rate":    0.5,
        }

    wallet = _resolve_judge_wallet(judge_wallet)
    if not wallet:
        return {
            "judge_id":          judge_wallet,
            "total_validations": 0,
            "agreement_count":   0,
            "agreement_rate":    0.5,
        }

    try:
        w3   = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 4}))
        c    = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_VALIDATION_ABI)
        rate, total = c.functions.getJudgeAgreementRate(
            Web3.to_checksum_address(wallet)
        ).call()
        return {
            "judge_id":          judge_wallet,
            "total_validations": total,
            "agreement_count":   round((rate / 100.0) * total),
            "agreement_rate":    rate / 100.0,
        }
    except Exception as exc:
        logger.warning("getJudgeAgreementRate RPC failed for %s: %s", judge_wallet, exc)
    return {
        "judge_id":          judge_wallet,
        "total_validations": 0,
        "agreement_count":   0,
        "agreement_rate":    0.5,
    }


# ── EigenTrust score — direct RPC (state variable) ────────────────────────────

def get_eigentrust_score(token_id: int) -> float | None:
    """Return EigenTrust score via direct RPC — ReputationRegistry.eigenTrustScore[tokenId]."""
    rpc  = settings.rpc_url
    addr = settings.reputation_registry_address
    if not rpc or not addr or not token_id:
        return None
    try:
        w3    = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 4}))
        c     = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_REPUTATION_ABI)
        score = c.functions.eigenTrustScore(token_id).call()
        return score / 100.0 if score else None
    except Exception as exc:
        logger.warning("eigenTrustScore RPC failed for tokenId %s: %s", token_id, exc)
        return None


# ── Reputation signals — The Graph (N users unbounded) ────────────────────────

def get_reputation_events(agent_token_id: int) -> list[dict]:
    """Return ReputationEvents from The Graph for a given token ID."""
    data = _gql("""
        query GetReputation($agentId: BigInt!) {
            reputationEvents(
                where: {agentId: $agentId}
                orderBy: blockNumber
                orderDirection: asc
            ) {
                id agentId clientAddress feedbackIndex
                value valueDecimals tag1 tag2
                endpoint feedbackURI blockNumber blockTimestamp transactionHash
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
        decimals   = int(ev.get("valueDecimals") or 0)
        raw        = int(ev.get("value") or 0)
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


# ── Escrow events — The Graph (timestamps pour audit/expiry) ─────────────────

def get_escrow_events_for_task(task_id: str) -> list[dict]:
    """Return EscrowEvents for a taskId — used for payment timestamp (access expiry)."""
    task_id_hash = Web3.keccak(text=task_id).hex()
    data = _gql("""
        query GetEscrowEvents($taskId: Bytes!) {
            escrowEvents(where: {taskId: $taskId}, orderBy: blockNumber) {
                id taskId eventType participant amount
                blockNumber blockTimestamp transactionHash
            }
        }
    """, {"taskId": task_id_hash})
    return data.get("escrowEvents") or []


# ── Validation response — direct RPC (state variable) ─────────────────────────

def get_validation_response(task_id: str) -> str | None:
    """Return responseURI via direct RPC — ValidationRegistry.getResponseURI()."""
    try:
        rpc  = settings.rpc_url
        addr = settings.validation_registry_address
        if not rpc or not addr:
            return None
        w3  = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 4}))
        c   = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_VALIDATION_ABI)
        uri = c.functions.getResponseURI(task_id).call()
        return uri if uri else None
    except Exception as exc:
        # 0x3e0100ea = TaskNotFound(string) — expected before validationRequest is mined
        if "0x3e0100ea" not in str(exc):
            logger.debug("get_validation_response RPC failed for %s: %s", task_id, exc)
        return None

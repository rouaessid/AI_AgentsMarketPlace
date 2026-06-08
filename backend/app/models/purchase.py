from __future__ import annotations
from pydantic import BaseModel


class PurchaseInfoResponse(BaseModel):
    task_id:        str
    agent_id:       str
    required_wei:   str
    required_eth:   float
    escrow_address: str
    call_data:      str


class PurchaseRequest(BaseModel):
    task_id:      str
    tx_hash:      str
    buyer_wallet: str


class PurchaseResponse(BaseModel):
    access_id:         str
    agent_id:          str
    task_id:           str
    status:            str
    validation_status: str
    message:           str = "Access granted — validation in progress"


class AccessStatus(BaseModel):
    agent_id:          str
    buyer_wallet:      str
    has_access:        bool
    task_id:           str | None = None
    validation_status: str | None = None


class JudgeVerdictOut(BaseModel):
    judge_id:               str
    judge_name:             str
    score:                  int | None = None
    verdict:                str | None = None
    justification_ipfs_cid: str | None = None


class ValidationStatusResponse(BaseModel):
    agent_id:          str
    val_task_id:       str | None = None
    status:            str | None = None
    consensus_verdict: str | None = None
    aggregated_score:  int | None = None
    justification_uri: str | None = None  # IPFS URI of aggregated judge justifications
    judges:            list[JudgeVerdictOut] = []
    started_at:        str | None = None

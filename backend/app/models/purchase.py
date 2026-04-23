from __future__ import annotations
from pydantic import BaseModel


class PurchaseInfoResponse(BaseModel):
    task_id:       str
    agent_id:      str
    required_wei:  str          # hex string for MetaMask
    required_eth:  float
    escrow_address: str
    call_data:     str          # encoded depositPayment() calldata for MetaMask


class PurchaseRequest(BaseModel):
    task_id:      str
    tx_hash:      str
    buyer_wallet: str


class PurchaseResponse(BaseModel):
    access_id:         str
    agent_id:          str
    task_id:           str
    tx_hash:           str
    status:            str      # "granted"
    validation_status: str      # "pending"
    message:           str = "Access granted — validation in progress"


class AccessStatus(BaseModel):
    agent_id:          str
    buyer_wallet:      str
    has_access:        bool
    task_id:           str | None = None
    tx_hash:           str | None = None
    validation_status: str | None = None   # pending / in_progress / validated / rejected


class JudgeVerdictOut(BaseModel):
    judge_id:      str
    judge_name:    str
    score:         int
    justification: str
    verdict:       str          # VALID | INVALID


class ValidationStatusResponse(BaseModel):
    agent_id:         str
    status:           str       # pending / in_progress / validated / rejected
    consensus_verdict: str | None = None
    aggregated_score: int | None = None
    judges:           list[JudgeVerdictOut] = []
    started_at:       str | None = None
    finished_at:      str | None = None

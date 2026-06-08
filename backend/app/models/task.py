from __future__ import annotations

from pydantic import BaseModel


class RunTaskRequest(BaseModel):
    prompt:       str
    buyer_wallet: str = ""
    agent_params: dict = {}


class RunTaskResponse(BaseModel):
    task_id: str
    mode:    str
    plan:    dict
    agents:  list[dict]
    status:  str


class PlanOnlyRequest(BaseModel):
    prompt:       str
    buyer_wallet: str = ""


class AlternativesRequest(BaseModel):
    subtask_description: str
    excluded_agent_ids:  list[str] = []
    limit:               int = 5


class PurchaseInfoRequest(BaseModel):
    task_id: str


class ExecuteRequest(BaseModel):
    task_id:      str
    prompt:       str = ""
    mode:         str = "pipeline"
    subtasks:     list[dict] = []
    agents:       list[dict] = []
    buyer_wallet: str = ""
    agent_params: dict = {}


class PackProposalsRequest(BaseModel):
    prompt:       str
    buyer_wallet: str = ""


class SelectPackRequest(BaseModel):
    pack_id:      str
    prompt:       str
    mode:         str
    reasoning:    str = ""
    subtasks:     list[dict]
    agents:       list[dict]
    buyer_wallet: str = ""
    pack_name:    str = ""


class ConfirmAccessRequest(BaseModel):
    buyer_wallet: str
    tx_hash:      str = ""

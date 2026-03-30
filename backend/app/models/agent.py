from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class AgentType(str, Enum):
    PROVIDER = "provider"
    JUDGE    = "judge"
    def to_uint8(self) -> int:
        return 0 if self == AgentType.PROVIDER else 1


class AgentStatus(str, Enum):
    ACTIVE    = "active"
    SUSPENDED = "suspended"
    REVOKED   = "revoked"


class ServiceEndpoint(BaseModel):
    name:     str
    endpoint: str
    version:  str | None = None
    skills:   list[str] | None = None
    domains:  list[str] | None = None


class AgentRegistrationEntry(BaseModel):
    agentId:       str
    tokenId:       int
    agentRegistry: str


class AgentRegistrationFile(BaseModel):
    type:           str = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
    name:           str
    description:    str
    image:          str | None = None
    version:        str = Field("1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    services:       list[ServiceEndpoint]        = Field(default_factory=list)
    x402Support:    bool                         = False
    active:         bool                         = True
    registrations:  list[AgentRegistrationEntry] = Field(default_factory=list)
    supportedTrust: list[str]                    = Field(default_factory=list)
    agent_type:     str | None                   = None
    capabilities:   dict[str, Any]               = Field(default_factory=dict)
    sandbox_config: dict[str, Any]               = Field(default_factory=dict)
    created_at:     str | None                   = None
    updated_at:     str | None                   = None


class AgentSubmitRequest(BaseModel):
    agent_id:        str = Field(..., min_length=3, max_length=64,
                                 pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
    name:            str = Field(..., min_length=3, max_length=128)
    description:     str = Field(..., min_length=10, max_length=2048)
    version:         str = Field("1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    agent_type:      AgentType = AgentType.PROVIDER
    image_url:       str | None = None
    owner_address:   str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    services:        list[ServiceEndpoint] = Field(default_factory=list)
    supported_trust: list[str] = Field(default_factory=lambda: ["reputation", "crypto-economic"])
    x402_support:    bool = False
    llm_model:       str  = "gpt-4o"
    framework:       str  = "langchain"
    language:        str  = "python"
    max_tokens:      int  = Field(8192, ge=256, le=128000)
    supported_tasks: list[str] = Field(default_factory=list)
    special_caps:    list[str] = Field(default_factory=list)
    price_per_task:  float     = Field(0.05, ge=0.0)
    runtime:         str  = "python:3.11"
    entrypoint:      str  = "main.py"
    cpu_limit:       int  = Field(1, ge=1, le=8)
    ram_limit_mb:    int  = Field(512, ge=128, le=8192)
    timeout_sec:     int  = Field(60, ge=5, le=600)
    env_var_keys:    list[str] = Field(default_factory=list)
    manifest_schema: str  = "default_v1"


class AgentNewVersionRequest(BaseModel):
    agent_id:      str
    owner_address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    new_version:   str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description:   str | None = None
    services:      list[ServiceEndpoint] | None = None
    capabilities:  dict[str, Any] | None = None
    active:        bool = True


class AgentOnChainConfirm(BaseModel):
    registration_id: str
    tx_hash:         str = Field(..., pattern=r"^0x[a-fA-F0-9]{64}$")
    token_id:        int | None = None


class UnsignedTx(BaseModel):
    contract_address: str
    function_name:    str
    abi_encoded_args: dict[str, Any]
    estimated_gas:    int = 300_000
    chain_id:         int


class AgentSubmitResponse(BaseModel):
    registration_id: str
    agent_id:        str
    status:          str = "pending_signature"
    ipfs_cid:        str
    agent_uri:       str
    metadata_hash:   str
    unsigned_tx:     UnsignedTx
    message:         str = "Signez registerAgent() avec votre wallet"


class AgentNewVersionResponse(BaseModel):
    registration_id: str
    agent_id:        str
    new_version:     str
    new_ipfs_cid:    str
    new_agent_uri:   str
    unsigned_tx:     UnsignedTx
    message:         str = "Signez mintNewVersion() avec votre wallet"


class AgentVersionInfo(BaseModel):
    token_id:  int
    version:   str
    agent_uri: str
    minted_at: datetime | None = None


class AgentRecord(BaseModel):
    id:                str
    agent_id:          str
    current_token_id:  int | None
    agent_registry:    str | None
    name:              str
    version:           str
    agent_type:        AgentType
    status:            AgentStatus
    owner_address:     str
    ipfs_cid:          str | None
    agent_uri:         str | None
    metadata_hash:     str | None
    zip_path:          str | None
    zip_hash:          str | None
    platform_endpoint: str | None = None
    tx_hash:           str | None
    registered_at:     datetime | None
    updated_at:        datetime
    versions:          list[AgentVersionInfo] = Field(default_factory=list)
    registration_file: AgentRegistrationFile | None = None

    model_config = {"from_attributes": True}
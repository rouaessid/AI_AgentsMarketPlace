from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

_VERSION_RE = r"^\d+\.\d+\.\d+$"


class AgentType(str, Enum):
    PROVIDER = "provider"
    JUDGE    = "judge"
    def to_uint8(self) -> int:
        return 0 if self == AgentType.PROVIDER else 1


class AgentStatus(str, Enum):
    ACTIVE            = "active"
    SUSPENDED         = "suspended"
    REVOKED           = "revoked"
    PENDING_SIGNATURE = "pending_signature"


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
    version:        str = Field("1.0.0", pattern=_VERSION_RE)
    readme:         str | None = None
    services:       list[ServiceEndpoint]        = Field(default_factory=list)
    x402Support:    bool                         = False
    active:         bool                         = True
    registrations:  list[AgentRegistrationEntry] = Field(default_factory=list)
    supportedTrust: list[str]                    = Field(default_factory=list)
    agent_type:     str | None                   = None
    capabilities:   dict[str, Any]               = Field(default_factory=dict)
    sandbox_config: dict[str, Any]               = Field(default_factory=dict)
    pricing:        dict[str, Any]               = Field(default_factory=dict)
    stake_amount:   float                        = 0.0
    created_at:     str | None                   = None
    updated_at:     str | None                   = None
    # Judge-specific fields (ignored for provider agents)
    evaluation_skills:      list[str] = Field(default_factory=list)
    validated_task_types:   list[str] = Field(default_factory=list)
    evaluation_domains:     list[str] = Field(default_factory=list)
    tools_used:             list[str] = Field(default_factory=list)
    evaluation_style:       str       = ""


class AgentSubmitRequest(BaseModel):
    agent_id:        str = Field(
        ..., min_length=3, max_length=64,
        pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$",
        description="Identifiant unique ex: search-1"
    )
    name:            str = Field(..., min_length=3, max_length=128)
    description:     str = Field(..., min_length=10, max_length=2048)
    version:         str = Field("1.0.0", pattern=_VERSION_RE)
    agent_type:      AgentType = AgentType.PROVIDER
    image_url:       str | None = None
    readme:          str | None = Field(
        None,
        description="README markdown : instructions, exemples, format output"
    )
    owner_address:   str = Field(
        ..., pattern=r"^0x[a-fA-F0-9]{40}$",
        description="Wallet connecte — fourni par le frontend automatiquement"
    )
    services:        list[ServiceEndpoint] = Field(default_factory=list)
    supported_trust: list[str] = Field(
        default_factory=lambda: ["reputation", "crypto-economic"]
    )
    x402_support:    bool = False
    llm_model:       str       = "llama-3.3-70b"
    framework:       str       = "raw_api"
    language:        str       = "python"
    max_tokens:      int       = Field(8192, ge=256, le=128000)
    supported_tasks: list[str] = Field(default_factory=list)
    special_caps:    list[str] = Field(default_factory=list)
    docker_image:    str = Field(
        ...,
        description="Image Docker Hub ex: username/my-agent:v1"
    )
    env_var_keys:    list[str] = Field(
        default_factory=list,
        description="Noms des vars d'env requises ex: ['GROQ_API_KEY', 'TAVILY_API_KEY']"
    )
    cpu_limit:       int   = Field(1, ge=1, le=8)
    ram_limit_mb:    int   = Field(512, ge=128, le=8192)
    timeout_sec:     int   = Field(60, ge=5, le=600)
    price_per_task:       float = Field(0.0001, ge=0.0, description="ETH par appel")
    access_duration_days: int   = Field(30, ge=1, description="Duree acces en jours")
    max_calls_per_day:    int   = Field(100, ge=1, description="Appels max par jour")
    stake_amount:    float = Field(
        0.002, ge=0.0,
        description="ETH a staker — StakingContract"
    )
    # Judge-specific capability fields (ignored for provider agents)
    evaluation_skills:      list[str] = Field(default_factory=list)
    validated_task_types:   list[str] = Field(default_factory=list)
    evaluation_domains:     list[str] = Field(default_factory=list)
    tools_used:             list[str] = Field(default_factory=list)
    evaluation_style:       str       = ""


class AgentNewVersionRequest(BaseModel):
    """
    New version = new code only.
    Triggers mintNewVersion() on-chain → new NFT token_id.
    Editorial changes (description, readme, price) go to AgentEditRequest.
    """
    agent_id:     str
    new_version:  str = Field(..., pattern=_VERSION_RE)
    docker_image: str = Field(..., description="Nouvelle image Docker ex: myagent:v2")


class AgentEditRequest(BaseModel):
    """
    Editorial/business changes — no blockchain tx, no new token.
    Updates DB + re-uploads IPFS manifest with new metadata.
    """
    description:    str | None = None
    readme:         str | None = None
    price_per_task: float | None = Field(None, ge=0.0)
    name:           str | None = None


class AgentOnChainConfirm(BaseModel):
    registration_id: str
    tx_hash:         str = Field(..., pattern=r"^0x[a-fA-F0-9]{64}$")
    token_id:        int | None = None


class UnsignedTx(BaseModel):
    contract_address: str
    function_name:    str
    abi_encoded_args: dict[str, Any]
    data:             str | None = None  # hex calldata for MetaMask eth_sendTransaction
    estimated_gas:    int = 300_000
    chain_id:         int


class AgentSubmitResponse(BaseModel):
    registration_id:   str
    agent_id:          str
    status:            str = "active"
    ipfs_cid:          str
    agent_uri:         str
    metadata_hash:     str
    token_id:          int | None        = None
    tx_hash:           str | None        = None   # IdentityRegistry tx (platform-signed)
    stake_tx_hash:     str | None        = None   # StakingContract tx (seller-signed via MetaMask)
    platform_endpoint: str | None        = None
    unsigned_tx:       UnsignedTx | None = None   # fallback when platform cannot sign
    # Seller must call StakingContract.stake() via MetaMask with this info
    stake_contract:    str | None        = None   # StakingContract address
    stake_amount_eth:  float             = 0.0    # amount seller must stake (ETH)
    message:           str               = "Agent enregistré et actif"


class AgentNewVersionResponse(BaseModel):
    registration_id: str
    agent_id:        str
    new_version:     str
    new_ipfs_cid:    str
    new_agent_uri:   str
    status:          str         = "pending_version"
    tx_hash:         str | None  = None          # platform-signed tx (blockchain available)
    unsigned_tx:     UnsignedTx | None = None    # fallback when blockchain unavailable
    message:         str = "Version soumise — en attente de confirmation blockchain"


class AgentVersionInfo(BaseModel):
    token_id:     int
    version:      str
    agent_uri:    str
    docker_image: str | None = None
    minted_at:    datetime | None = None


class AgentRecord(BaseModel):
    id:                   str
    agent_id:             str
    current_token_id:     int | None
    agent_registry:       str | None
    name:                 str
    version:              str
    agent_type:           AgentType
    status:               AgentStatus
    owner_address:        str
    ipfs_cid:             str | None
    agent_uri:            str | None
    metadata_hash:        str | None
    docker_image:         str | None = None
    platform_endpoint:    str | None = None
    stake_amount:         float      = 0.0
    price_per_task:       float      = 0.0
    access_duration_days: int        = 30
    max_calls_per_day:    int        = 100
    tx_hash:              str | None
    registered_at:        datetime | None
    updated_at:           datetime
    versions:             list[AgentVersionInfo]       = Field(default_factory=list)
    registration_file:    AgentRegistrationFile | None = None

    model_config = {"from_attributes": True}


class RunRequest(BaseModel):
    task_id:      str | None = None
    prompt:       str = Field(..., description="La tache a executer")
    params:       dict[str, Any] = Field(
        default_factory=dict,
        description="Cles API requises ex: {'GROQ_API_KEY': '...', 'TAVILY_API_KEY': '...'}"
    )
    buyer_wallet: str | None = Field(
        None,
        description="Wallet du buyer — si present et access verifie, declenche la validation"
    )
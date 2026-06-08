from __future__ import annotations
from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    app_name:    str  = "AgentMarket API"
    environment: str  = "development"
    debug:       bool = True

    storage_path:    str = "/tmp/agentmarket"
    max_zip_size_mb: int = 500
    database_url:    str = ""

    use_ipfs:       bool = False
    pinata_api_key: str  = ""
    pinata_secret:  str  = ""
    ipfs_gateway:   str  = "https://gateway.pinata.cloud/ipfs"

    rpc_url:                   str = "http://127.0.0.1:8545"
    chain_id:                  int = 31337
    identity_registry_address: str = ""
    platform_private_key:      str = ""
    platform_wallet_address:   str = ""
    staking_contract_address:   str = ""
    validation_registry_address: str = ""
    escrow_manager_address:      str = ""
    reputation_registry_address: str = ""

    # Feedback wallet — must NOT be the deployer (platform) wallet.
    # The deployer owns all agent tokens; giveFeedback() rejects the token owner.
    # Default = hardhat/Anvil account[1] (well-known, safe for local testing only).
    feedback_wallet_key_testnet: str = ""
    # feedback_wallet_key : testnet prend priorité sur la valeur hardcodée Hardhat
    @property
    def feedback_wallet_key(self) -> str:
        return self.feedback_wallet_key_testnet or "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

    # Judge keys — dict wallet_address → private_key (source primaire)
    # Ex: JUDGE_WALLET_KEYS={"0x90F79...":"0x7c852...","0xAutre...":"0xClé..."}
    judge_wallet_keys: dict[str, str] = {}

    # Backwards-compat — dérivés automatiquement si judge_wallet_keys est vide
    judge_1_private_key: str = ""
    judge_2_private_key: str = ""
    judge_3_private_key: str = ""
    judge_1_id: str = "judge-alpha"
    judge_2_id: str = "judge-beta"
    judge_3_id: str = "judge-gamma"

    # Platform LLM keys — used by planner_service, matching_service
    groq_api_key:   str = ""
    tavily_api_key: str = ""

    # Writer agent Tavily key — injected automatically into pipeline agent containers
    writer_tavily_key: str = ""

    # Judge LLM API keys (separate to avoid quota collisions)
    judge_alpha_groq_key:     str = ""
    judge_alpha_tavily_key:   str = ""
    judge_beta_groq_key:      str = ""
    judge_gamma_groq_key:     str = ""
    judge_delta_groq_key:     str = ""
    judge_epsilon_groq_key:   str = ""

    # Gemini API keys — gamma + delta
    gemini_api_key:        str = ""
    judge_delta_gemini_key: str = ""

    # Mistral API keys — gamma + delta
    judge_gamma_mistral_key: str = ""
    judge_delta_mistral_key: str = ""

    # OpenRouter API keys — beta + gamma + epsilon
    judge_beta_or_key:     str = ""
    judge_gamma_or_key:    str = ""
    judge_epsilon_or_key:  str = ""

    sandbox_backend:  str = "docker"
    sandbox_network:  str = "none"
    sandbox_work_dir: str = "/tmp/agentmarket/sandbox"

    # Tunnel public
    tunnel_provider:  str = "cloudflare"
    tunnel_base_url:  str = ""

    # Ngrok legacy
    ngrok_authtoken:  str = ""
    ngrok_base_url:   str = ""

    backend_port:     int = 8000

    # JWT secret for SIWE auth tokens — override in .env with a strong random value
    jwt_secret: str = "change-me-in-production-use-a-long-random-string"

    allowed_origins: list[str] = ["*"]

    # The Graph subgraph endpoint — used instead of blockchain_indexer
    graph_url: str = "https://api.studio.thegraph.com/query/1753968/agentmarket/v5.1.0"

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str) and value.lower() in {"release", "prod", "production"}:
            return False
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

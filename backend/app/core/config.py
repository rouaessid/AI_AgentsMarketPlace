from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env", env_file_encoding="utf-8", case_sensitive=False
    )

    app_name:    str  = "AgentMarket API"
    environment: str  = "development"
    debug:       bool = True

    storage_path:    str = "/tmp/agentmarket"
    max_zip_size_mb: int = 500

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

    # Judge LLM API keys (separate to avoid quota collisions)
    judge_alpha_groq_key:   str = ""
    judge_alpha_tavily_key: str = ""
    judge_beta_groq_key:    str = ""
    judge_gamma_groq_key:   str = ""

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

    allowed_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
from __future__ import annotations
import json
import requests
from pathlib import Path
from dotenv import dotenv_values

env = dotenv_values(Path(__file__).parent.parent / ".env")
BACKEND_URL = env.get("BACKEND_URL", "http://localhost:8000")


def get_tunnel_info() -> dict:
    try:
        return requests.get(f"{BACKEND_URL}/tunnel", timeout=5).json()
    except Exception:
        return {"tunnel_url": None, "endpoints": {}}


def get_all_agents() -> list[dict]:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/v1/agents", timeout=5)
        return resp.json().get("agents", [])
    except Exception:
        return []


def get_agent(agent_id: str) -> dict | None:
    try:
        resp = requests.get(f"{BACKEND_URL}/api/v1/agents/{agent_id}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def get_agent_readme(agent_id: str) -> dict | None:
    try:
        resp = requests.get(
            f"{BACKEND_URL}/api/v1/agents/{agent_id}/readme", timeout=5
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def register_agent(data: dict) -> dict:
    resp = requests.post(
        f"{BACKEND_URL}/api/v1/agents/register",
        data={"data": json.dumps(data)},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def confirm_agent(registration_id: str, tx_hash: str, token_id: int) -> dict:
    resp = requests.post(
        f"{BACKEND_URL}/api/v1/agents/confirm",
        json={
            "registration_id": registration_id,
            "tx_hash":         tx_hash,
            "token_id":        token_id,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def run_agent(agent_id: str, prompt: str, params: dict) -> dict:
    tunnel = get_tunnel_info()
    endpoint = tunnel.get("endpoints", {}).get(agent_id)
    if not endpoint:
        endpoint = f"{BACKEND_URL}/api/v1/agents/{agent_id}/run"
    resp = requests.post(
        endpoint,
        json={"prompt": prompt, "params": params},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def get_agents_by_owner(owner_address: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{BACKEND_URL}/api/v1/agents/owner/{owner_address}",
            timeout=5
        )
        return resp.json().get("agents", [])
    except Exception:
        return []
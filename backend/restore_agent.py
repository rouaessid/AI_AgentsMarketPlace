"""
restore_agent.py
================
Restaure tous les agents en memoire depuis agent_state.json.
Lance depuis backend/ apres chaque redemarrage uvicorn :

  python restore_agent.py

Ne necessite pas de relancer Hardhat ni de refaire register_agent.js.
Le tx_hash et token_id sont lus depuis agent_state.json.
"""
import json
import sys
import requests
from pathlib import Path

BASE_URL   = "http://localhost:8000"
STATE_FILE = Path("C:/tmp/agentmarket/agent_state.json")


def restore():
    if not STATE_FILE.exists():
        print("agent_state.json introuvable — rien a restaurer")
        print("Faire d'abord /register + /confirm via Swagger")
        sys.exit(0)

    agents = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not agents:
        print("Aucun agent dans agent_state.json")
        sys.exit(0)

    print(f"Restauration de {len(agents)} agent(s)...\n")

    for agent in agents:
        print(f"── {agent['agent_id']} ──────────────────────")

        # Extraire le tag sans le digest pour /register
        docker_tag = agent["docker_image"].split("@")[0]

        # 1. Register
        resp = requests.post(
            f"{BASE_URL}/api/v1/agents/register",
            data={"data": json.dumps({
                "agent_id":            agent["agent_id"],
                "name":                agent["name"],
                "description":         agent["description"],
                "version":             agent["version"],
                "agent_type":          "provider",
                "owner_address":       agent["owner_address"],
                "readme":              agent.get("readme", ""),
                "docker_image":        docker_tag,
                "env_var_keys":        agent["env_var_keys"],
                "llm_model":           agent.get("llm_model", "llama-3.3-70b"),
                "framework":           "raw_api",
                "language":            "python",
                "supported_tasks":     agent.get("supported_tasks", []),
                "special_caps":        agent.get("special_caps", []),
                "price_per_task":      agent["price_per_task"],
                "access_duration_days": agent["access_duration_days"],
                "max_calls_per_day":   agent["max_calls_per_day"],
                "stake_amount":        agent["stake_amount"],
                "cpu_limit":           agent["cpu_limit"],
                "ram_limit_mb":        agent["ram_limit_mb"],
                "timeout_sec":         agent["timeout_sec"],
            })}
        )

        if resp.status_code != 201:
            print(f"  ERREUR register: {resp.text}")
            continue

        registration_id = resp.json()["registration_id"]
        print(f"  registration_id : {registration_id}")

        # 2. Confirm avec tx_hash + token_id sauvegardés
        resp2 = requests.post(
            f"{BASE_URL}/api/v1/agents/confirm",
            json={
                "registration_id": registration_id,
                "tx_hash":         agent["tx_hash"],
                "token_id":        agent["token_id"],
            }
        )

        if resp2.status_code != 200:
            print(f"  ERREUR confirm: {resp2.text}")
            continue

        result = resp2.json()
        print(f"  docker_image     : {result['docker_image']}")
        print(f"  platform_endpoint: {result['platform_endpoint']}")
        print(f"  current_token_id : {result['current_token_id']}")
        print(f"  ✅ Restaure\n")

    print("══════════════════════════════════════")
    print("Tous les agents sont restaures ✅")
    print("Pret pour /run")


if __name__ == "__main__":
    restore()
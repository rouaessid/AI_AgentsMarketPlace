"""
Fix judges in DB:
- Set docker_image column from manifest
- Set identity_metadata from manifest (proper AgentRegistrationFile structure)
"""
import json, sqlite3
from pathlib import Path

DB = Path("C:/tmp/agentmarket/agentmarket.db")
JUDGES = ["judge-alpha", "judge-beta", "judge-gamma"]

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

for jid in JUDGES:
    manifest_path = Path(f"agents/{jid}/manifest.json")
    if not manifest_path.exists():
        print(f"SKIP {jid} — manifest not found at {manifest_path}")
        continue

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    docker_image = data.get("docker_image", "")

    # Build proper identity_metadata compatible with AgentRegistrationFile
    meta = {
        "type": data.get("type", "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"),
        "name": data.get("name", jid),
        "description": data.get("description", ""),
        "version": data.get("version", "1.0.0"),
        "agent_type": data.get("agent_type", "judge"),
        "registrations": data.get("registrations", []),
        "supportedTrust": data.get("supportedTrust", []),
        "capabilities": {
            "llm_model": data.get("llm_model", ""),
            "framework": data.get("framework", ""),
            "language": data.get("language", "python"),
            "supported_tasks": data.get("supported_tasks", []),
            "special_caps": data.get("special_caps", []),
            "env_var_keys": data.get("env_var_keys", []),
        },
        "sandbox_config": {
            "docker_image": docker_image,
            "cpu_limit": data.get("cpu_limit", 1),
            "ram_limit_mb": data.get("ram_limit_mb", 512),
            "timeout_sec": data.get("timeout_sec", 120),
            "env_var_keys": data.get("env_var_keys", []),
        },
        "services": data.get("services", []),
        "pricing": data.get("pricing", {}),
        "stake_amount": data.get("stake_amount", 0.0),
    }

    conn.execute(
        "UPDATE agents SET docker_image = ?, identity_metadata = ? WHERE agent_id = ?",
        (docker_image, json.dumps(meta), jid),
    )
    print(f"Fixed {jid} — docker_image={docker_image}")

conn.commit()
conn.close()
print("\nDone. Restart the backend.")

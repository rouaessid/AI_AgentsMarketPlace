import sqlite3, json
from pathlib import Path

for p in ["C:/tmp/agentmarket/agentmarket.db", "/tmp/agentmarket/agentmarket.db"]:
    db = Path(p)
    if db.exists():
        print(f"DB found: {db}")
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT identity_metadata FROM agents WHERE agent_id = ?", ("researcher-01",)
        ).fetchone()
        if row and row["identity_metadata"]:
            meta = json.loads(row["identity_metadata"])
            caps = meta.get("capabilities", {})
            sand = meta.get("sandbox_config", {})
            print("capabilities.env_var_keys :", caps.get("env_var_keys", "MISSING"))
            print("sandbox_config.env_var_keys:", sand.get("env_var_keys", "MISSING"))
            print("top-level env_var_keys     :", meta.get("env_var_keys", "MISSING"))
        else:
            print("Row not found or metadata empty")
        conn.close()
        break
else:
    print("DB not found in any known path")

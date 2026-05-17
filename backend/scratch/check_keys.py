import sqlite3
import json
import os

db_path = 'C:/tmp/agentmarket/agentmarket.db'
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT agent_id, identity_metadata FROM agents WHERE status='active' AND agent_type != 1")
rows = cursor.fetchall()
if not rows:
    print("No active provider agents found in DB.")
else:
    for row in rows:
        agent_id, meta_raw = row
        if meta_raw:
            meta = json.loads(meta_raw)
            caps = meta.get("capabilities", {})
            sand = meta.get("sandbox_config", {})
            env_var_keys = caps.get("env_var_keys") or sand.get("env_var_keys") or []
            print(f"Agent {agent_id}: env_var_keys={env_var_keys}")
        else:
            print(f"Agent {agent_id}: No metadata")

conn.close()

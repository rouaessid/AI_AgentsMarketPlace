import sqlite3, json
from pathlib import Path

DB = Path("C:/tmp/agentmarket/agentmarket.db")
conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT identity_metadata FROM agents WHERE agent_id = ?", ("researcher-01",)).fetchone()
conn.close()

if row and row["identity_metadata"]:
    meta = json.loads(row["identity_metadata"])
    print("=== TOP-LEVEL KEYS ===")
    print(list(meta.keys()))
    print()
    caps = meta.get("capabilities", "KEY_MISSING")
    sand = meta.get("sandbox_config", "KEY_MISSING")
    print("=== capabilities ===")
    print(json.dumps(caps, indent=2) if isinstance(caps, dict) else caps)
    print()
    print("=== sandbox_config ===")
    print(json.dumps(sand, indent=2) if isinstance(sand, dict) else sand)
else:
    print("No metadata")

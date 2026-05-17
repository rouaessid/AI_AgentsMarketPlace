"""
Patch env_var_keys for researcher-01 in DB identity_metadata.
Run once then restart backend.
"""
import sqlite3, json, sys
from pathlib import Path

# Cross-platform: /tmp/agentmarket on Linux/Mac, C:/tmp/agentmarket on Windows
candidates = [
    Path("/tmp/agentmarket/agentmarket.db"),
    Path("C:/tmp/agentmarket/agentmarket.db"),
]
DB = next((p for p in candidates if p.exists()), None)
if DB is None:
    print("ERROR: DB not found. Tried:", [str(p) for p in candidates])
    sys.exit(1)

AGENT_ID = "researcher-01"
KEYS = ["GROQ_API_KEY", "TAVILY_API_KEY"]

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

row = conn.execute("SELECT identity_metadata FROM agents WHERE agent_id = ?", (AGENT_ID,)).fetchone()
if not row:
    print(f"Agent '{AGENT_ID}' not found in DB"); conn.close(); sys.exit(1)

meta = json.loads(row["identity_metadata"]) if row["identity_metadata"] else {}

# Patch both locations
if "capabilities" in meta:
    meta["capabilities"]["env_var_keys"] = KEYS
if "sandbox_config" in meta:
    meta["sandbox_config"]["env_var_keys"] = KEYS
# Also patch top-level env_var_keys if present
meta["env_var_keys"] = KEYS

conn.execute(
    "UPDATE agents SET identity_metadata = ? WHERE agent_id = ?",
    (json.dumps(meta), AGENT_ID)
)
conn.commit()
conn.close()
print(f"Done — env_var_keys set to {KEYS} for {AGENT_ID}")
print(f"DB: {DB}")
print("Restart the backend now.")

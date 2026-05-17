"""
Reset agent status → pending_signature so the Retry Registration button appears.
Usage: python reset_agents_status.py [agent_id1 agent_id2 ...]
       (no args = reset ALL agents that are active)
"""
import sqlite3, sys
from pathlib import Path

DB_PATH = Path("/tmp/agentmarket/agentmarket.db")

if not DB_PATH.exists():
    print(f"[ERROR] DB not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

agent_ids = sys.argv[1:] if len(sys.argv) > 1 else None

if agent_ids:
    rows = conn.execute(
        "SELECT agent_id, status FROM agents WHERE agent_id IN ({})".format(
            ",".join("?" * len(agent_ids))
        ), agent_ids
    ).fetchall()
else:
    rows = conn.execute("SELECT agent_id, status FROM agents WHERE status = 'active'").fetchall()

if not rows:
    print("No agents found.")
    conn.close()
    sys.exit(0)

print("Agents to reset:")
for r in rows:
    print(f"  {r['agent_id']:30s}  status={r['status']}")

confirm = input("\nReset these to pending_signature? [y/N] ").strip().lower()
if confirm != 'y':
    print("Aborted.")
    conn.close()
    sys.exit(0)

ids = [r['agent_id'] for r in rows]
conn.execute(
    "UPDATE agents SET status = 'pending_signature' WHERE agent_id IN ({})".format(
        ",".join("?" * len(ids))
    ), ids
)
conn.commit()
print(f"Done — {len(ids)} agent(s) reset to pending_signature.")
print("Restart the backend now so the in-memory cache reloads from DB.")
conn.close()

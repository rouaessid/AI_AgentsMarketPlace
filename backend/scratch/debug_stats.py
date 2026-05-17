import sqlite3
import json
from pathlib import Path

# On cherche la DB dans C:\tmp\agentmarket\agentmarket.db ou via le chemin relatif
db_path = Path("C:/tmp/agentmarket/agentmarket.db")
if not db_path.exists():
    db_path = Path("backend/agentmarket.db") # Fallback local

print(f"Checking DB: {db_path}")
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT agent_id, metadata FROM agents").fetchall()
for r in rows:
    print(f"\nAgent: {r['agent_id']}")
    if r['metadata']:
        meta = json.loads(r['metadata'])
        caps = meta.get('capabilities', {})
        print(f" - Tasks Performed: {caps.get('tasks_performed')}")
        print(f" - Monthly Tasks: {caps.get('monthly_tasks')}")
        print(f" - Weekly Success: {caps.get('weekly_success')}")
    else:
        print(" - Metadata: NULL")

conn.close()

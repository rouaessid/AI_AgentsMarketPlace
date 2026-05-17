import sqlite3
import json
import os

db_path = 'C:/tmp/agentmarket/agentmarket.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT id, task_prompt, selected_agents_json FROM pipeline_tasks ORDER BY created_at DESC LIMIT 5")
for row in cursor.fetchall():
    tid, prompt, agents_json = row
    print(f"Task {tid} ({prompt[:30]}...):")
    try:
        agents = json.loads(agents_json) if agents_json else []
        for a in agents:
            keys = a.get('env_var_keys', 'MISSING')
            print(f"  - Agent {a.get('agent_id')}: keys={keys}")
    except:
        print(f"  - Error parsing agents_json")

conn.close()

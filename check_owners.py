import sqlite3
conn = sqlite3.connect("C:/tmp/agentmarket/agentmarket.db")
cur = conn.cursor()
cur.execute("SELECT agent_id, agent_type, owner_address FROM agents")
for row in cur.fetchall():
    print(row)
conn.close()

import sqlite3
path = "/tmp/agentmarket/agentmarket.db"
conn = sqlite3.connect(path)
cur = conn.cursor()

print("=== pipeline_tasks ===")
cur.execute("PRAGMA table_info(pipeline_tasks)")
cols = [r[1] for r in cur.fetchall()]
print("cols:", cols)
cur.execute("SELECT * FROM pipeline_tasks ORDER BY created_at DESC LIMIT 10")
for r in cur.fetchall():
    print(r)

print()
print("=== collaboration_log mode breakdown ===")
cur.execute("SELECT mode, COUNT(*), AVG(score) FROM collaboration_log GROUP BY mode")
for r in cur.fetchall():
    print(f"mode={r[0]}: count={r[1]}, avg_score={r[2]}")

print()
print("=== validation_sessions ===")
cur.execute("PRAGMA table_info(validation_sessions)")
cols2 = [r[1] for r in cur.fetchall()]
print("cols:", cols2)
cur.execute("SELECT agent_id, status, consensus_verdict, aggregated_score, started_at FROM validation_sessions ORDER BY started_at DESC LIMIT 20")
for r in cur.fetchall():
    print(r)

import sqlite3

conn = sqlite3.connect("agentmarket.db")
conn.row_factory = sqlite3.Row

print("=== TABLES ===")
for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(" ", r[0])

print("\n=== PIPELINE TASKS (last 3) ===")
try:
    for r in conn.execute("SELECT id, status, created_at FROM pipeline_tasks ORDER BY created_at DESC LIMIT 3"):
        print(f"  {r['id']} | {r['status']} | {r['created_at']}")
except Exception as e:
    print("  ERROR:", e)

print("\n=== VALIDATION SESSIONS (last 8) ===")
try:
    for r in conn.execute("SELECT agent_id, val_task_id, status, consensus_verdict, aggregated_score, started_at FROM validation_sessions ORDER BY started_at DESC LIMIT 8"):
        print(f"  {r['agent_id']} | {r['status']} | {r['consensus_verdict']} ({r['aggregated_score']}) | {r['started_at']}")
except Exception as e:
    print("  ERROR:", e)

print("\n=== JUDGE VERDICTS (last 15) ===")
try:
    for r in conn.execute("SELECT agent_id, judge_id, verdict, score, created_at FROM judge_verdicts ORDER BY created_at DESC LIMIT 15"):
        print(f"  {r['agent_id']} | {r['judge_id']} | {r['verdict']} {r['score']} | {r['created_at']}")
except Exception as e:
    print("  ERROR:", e)

print("\n=== ACTIVE JUDGES ===")
try:
    for r in conn.execute("SELECT agent_id, status, agent_type, docker_image FROM agents WHERE agent_type='judge' OR agent_type=1"):
        print(f"  {r['agent_id']} | type={r['agent_type']} | status={r['status']} | img={r['docker_image']}")
except Exception as e:
    print("  ERROR:", e)

conn.close()

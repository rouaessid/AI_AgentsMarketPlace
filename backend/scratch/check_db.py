import sqlite3
import os

DB_PATH = "C:/tmp/agentmarket/agentmarket.db"

def query():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- VALIDATION SESSIONS ---")
    sessions = cursor.execute("SELECT * FROM validation_sessions").fetchall()
    for s in sessions:
        print(dict(s))
        
    print("\n--- JUDGE VERDICTS ---")
    verdicts = cursor.execute("SELECT judge_id, verdict, justification FROM judge_verdicts").fetchall()
    for v in verdicts:
        print(dict(v))
        
    conn.close()

if __name__ == "__main__":
    query()

"""
migrate_db.py — One-time migration from old raw-SQLite schema to new SQLAlchemy schema.

Run once:  python migrate_db.py

What it does:
  1. Renames agents.token_id     → current_token_id
  2. Renames agents.metadata     → identity_metadata
  3. Adds missing columns to agents (block_number, agent_uri, ipfs_cid,
     name, version, price_per_task, stake_amount)
  4. Creates all new tables (agent_versions, agent_telemetry, escrow_events,
     staking_events, validation_events, reputation_events, indexer_state)
  5. Seeds agent_telemetry with zeroes for existing agents
  6. Backfills name/version from identity_metadata JSON if present
"""
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/tmp/agentmarket/agentmarket.db")

if not DB_PATH.exists():
    print(f"[INFO] DB not found at {DB_PATH} — nothing to migrate.")
    sys.exit(0)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print(f"[MIGRATE] DB: {DB_PATH}")

# ── Step 1: rename agents.token_id → current_token_id ────────────────────────
existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(agents)").fetchall()]
print(f"[MIGRATE] agents columns before: {existing_cols}")

if "token_id" in existing_cols and "current_token_id" not in existing_cols:
    cur.execute("ALTER TABLE agents RENAME COLUMN token_id TO current_token_id")
    print("[MIGRATE] ✓ renamed token_id → current_token_id")
else:
    print("[MIGRATE] ✓ current_token_id already exists (skipped)")

# ── Step 2: rename agents.metadata → identity_metadata ───────────────────────
existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(agents)").fetchall()]
if "metadata" in existing_cols and "identity_metadata" not in existing_cols:
    cur.execute("ALTER TABLE agents RENAME COLUMN metadata TO identity_metadata")
    print("[MIGRATE] ✓ renamed metadata → identity_metadata")
else:
    print("[MIGRATE] ✓ identity_metadata already exists (skipped)")

# ── Step 3: add missing columns to agents ────────────────────────────────────
new_cols = [
    ("block_number",    "INTEGER"),
    ("agent_uri",       "TEXT"),
    ("name",            "TEXT"),
    ("version",         "TEXT"),
    ("price_per_task",  "REAL DEFAULT 0.0"),
    ("stake_amount",    "REAL DEFAULT 0.0"),
]
existing_cols = [r[1] for r in cur.execute("PRAGMA table_info(agents)").fetchall()]
for col, col_type in new_cols:
    if col not in existing_cols:
        cur.execute(f"ALTER TABLE agents ADD COLUMN {col} {col_type}")
        print(f"[MIGRATE] ✓ added agents.{col}")
    else:
        print(f"[MIGRATE] ✓ agents.{col} already exists (skipped)")

# ── Step 4: create new tables (idempotent) ───────────────────────────────────

cur.execute("""
CREATE TABLE IF NOT EXISTS agent_versions (
    token_id     INTEGER PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    version      TEXT NOT NULL,
    agent_uri    TEXT,
    docker_image TEXT,
    block_number INTEGER,
    minted_at    TEXT
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS agent_telemetry (
    agent_id             TEXT PRIMARY KEY,
    tasks_performed      INTEGER NOT NULL DEFAULT 0,
    usage_count          INTEGER NOT NULL DEFAULT 0,
    avg_response_time    REAL,
    task_completion_rate REAL,
    uptime               REAL,
    last_active          TEXT,
    monthly_tasks_json   TEXT,
    weekly_success_json  TEXT
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS escrow_events (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    agent_id     TEXT,
    client       TEXT,
    provider     TEXT,
    amount_wei   TEXT,
    tx_hash      TEXT,
    block_number INTEGER,
    created_at   TEXT
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS staking_events (
    id           TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    agent_wallet TEXT NOT NULL,
    amount_wei   TEXT,
    reason       TEXT,
    tx_hash      TEXT,
    block_number INTEGER,
    created_at   TEXT
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS validation_events (
    id           TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    agent_id     TEXT,
    event_type   TEXT NOT NULL,
    verdict      TEXT,
    score        REAL,
    judge_id     TEXT,
    tx_hash      TEXT,
    block_number INTEGER,
    created_at   TEXT
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS reputation_events (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    reputation_score REAL,
    success_rate     REAL,
    tx_hash          TEXT,
    block_number     INTEGER,
    created_at       TEXT
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS indexer_state (
    contract_name TEXT PRIMARY KEY,
    last_block    INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT
)""")

print("[MIGRATE] ✓ new tables created (or already existed)")

# ── Step 5: seed agent_telemetry for existing agents ────────────────────────
agents = cur.execute("SELECT agent_id FROM agents").fetchall()
for row in agents:
    aid = row[0]
    exists = cur.execute(
        "SELECT 1 FROM agent_telemetry WHERE agent_id = ?", (aid,)
    ).fetchone()
    if not exists:
        cur.execute("""
            INSERT INTO agent_telemetry (agent_id, tasks_performed, usage_count,
                monthly_tasks_json, weekly_success_json)
            VALUES (?, 0, 0, ?, ?)
        """, (aid, json.dumps([0]*12), json.dumps([0]*7)))
        print(f"[MIGRATE] ✓ seeded agent_telemetry for {aid}")

# ── Step 6: backfill name/version from identity_metadata JSON ────────────────
agents = cur.execute(
    "SELECT agent_id, identity_metadata FROM agents WHERE name IS NULL"
).fetchall()
for row in agents:
    aid, meta_json = row[0], row[1]
    if not meta_json:
        continue
    try:
        meta = json.loads(meta_json)
        name    = meta.get("name")
        version = meta.get("version")
        pricing = meta.get("pricing") or {}
        price   = pricing.get("price_per_task", 0.0)
        stake   = meta.get("stake_amount", 0.0)
        if name:
            cur.execute("""
                UPDATE agents SET name=?, version=?, price_per_task=?, stake_amount=?
                WHERE agent_id=?
            """, (name, version, price, stake, aid))
            print(f"[MIGRATE] ✓ backfilled name='{name}' version='{version}' for {aid}")
    except Exception as e:
        print(f"[MIGRATE] ⚠ backfill failed for {aid}: {e}")

conn.commit()
conn.close()
print("\n[MIGRATE] Migration terminée. La DB est compatible avec le nouveau schéma.")
print("[MIGRATE] Lance le backend normalement : uvicorn app.main:app --reload --port 8000")

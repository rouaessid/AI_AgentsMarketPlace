"""
fix_agent_metadata.py
Patches identity_metadata for agents that were registered before the judge
capability fields (evaluation_skills, evaluation_domains, tools_used,
evaluation_style) were added to AgentRegistrationFile.

Also recomputes capability_embedding for all agents.

Run once:  python backend/fix_agent_metadata.py
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH      = Path("C:/tmp/agentmarket/agentmarket.db")
AGENTS_DIR   = PROJECT_ROOT / "agents"

# Extra capability fields from each agent's manifest.json (ground truth)
MANIFEST_CAPS: dict[str, dict] = {}
for manifest_path in AGENTS_DIR.glob("*/manifest.json"):
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        agent_id = m.get("agent_id")
        if agent_id:
            MANIFEST_CAPS[agent_id] = {
                "evaluation_skills":    m.get("evaluation_skills", []),
                "validated_task_types": m.get("validated_task_types", []),
                "evaluation_domains":   m.get("evaluation_domains", []),
                "tools_used":           m.get("tools_used", []),
                "evaluation_style":     m.get("evaluation_style", ""),
            }
    except Exception as e:
        print(f"  WARN: could not read {manifest_path}: {e}")

print(f"Loaded manifests for: {list(MANIFEST_CAPS.keys())}\n")

# ── Patch identity_metadata ────────────────────────────────────────────────────
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT agent_id, identity_metadata FROM agents").fetchall()
patched = []

for row in rows:
    agent_id = row["agent_id"]
    extra = MANIFEST_CAPS.get(agent_id)
    if not extra:
        print(f"  SKIP {agent_id} (no manifest found)")
        continue

    meta = {}
    if row["identity_metadata"]:
        try:
            meta = json.loads(row["identity_metadata"])
        except Exception:
            pass

    changed = False
    for key, val in extra.items():
        if meta.get(key) != val:
            meta[key] = val
            changed = True

    if changed:
        conn.execute(
            "UPDATE agents SET identity_metadata = ? WHERE agent_id = ?",
            (json.dumps(meta), agent_id),
        )
        patched.append(agent_id)
        print(f"  PATCHED {agent_id}")
    else:
        print(f"  OK     {agent_id} (already up to date)")

conn.commit()
conn.close()
print(f"\n{len(patched)} agent(s) patched: {patched}")

# ── Recompute embeddings ───────────────────────────────────────────────────────
print("\nRecomputing embeddings...")
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
os.environ.setdefault("STORAGE_PATH", "C:/tmp/agentmarket")

try:
    from app.services.matching_service import embed_agent_capabilities

    conn2 = sqlite3.connect(str(DB_PATH))
    conn2.row_factory = sqlite3.Row
    rows2 = conn2.execute("SELECT agent_id, identity_metadata FROM agents").fetchall()
    conn2.close()

    for row in rows2:
        if not row["identity_metadata"]:
            print(f"  SKIP {row['agent_id']} (no metadata)")
            continue
        try:
            meta = json.loads(row["identity_metadata"])
            vec = embed_agent_capabilities(row["agent_id"], meta)
            print(f"  EMBED {row['agent_id']} dim={len(vec)}")
        except Exception as e:
            print(f"  FAIL  {row['agent_id']}: {e}")

    print("\nDone.")
except ImportError as e:
    print(f"\nCould not import matching_service (FlagEmbedding may not be installed): {e}")
    print("Embeddings will be computed automatically when agents run a task.")

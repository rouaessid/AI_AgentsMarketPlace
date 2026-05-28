"""
Find all IPFS local files for researcher-01 and remove PINATA_JWT + AGENT_PRIVATE_KEY
from env_var_keys in capabilities and sandbox_config.
Also fix the DB identity_metadata to be a proper AgentRegistrationFile structure.
"""
import json, sqlite3
from pathlib import Path

KEEP = ["GROQ_API_KEY", "TAVILY_API_KEY"]
REMOVE = {"PINATA_JWT", "AGENT_PRIVATE_KEY"}
AGENT_ID = "researcher-01"
IPFS_DIR = Path("C:/tmp/agentmarket/ipfs_local")
DB = Path("C:/tmp/agentmarket/agentmarket.db")

patched_files = 0
full_meta = None

# ── 1. Patch IPFS local files ─────────────────────────────────────────────────
for f in IPFS_DIR.glob("*.json"):
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        continue

    regs = data.get("registrations", [])
    is_researcher = any(r.get("agentId") == AGENT_ID for r in regs)
    if not is_researcher:
        continue

    changed = False

    for loc in ["capabilities", "sandbox_config"]:
        section = data.get(loc, {})
        keys = section.get("env_var_keys", [])
        if any(k in REMOVE for k in keys):
            section["env_var_keys"] = [k for k in keys if k not in REMOVE]
            data[loc] = section
            changed = True

    # Also fix top-level env_var_keys if present
    top = data.get("env_var_keys", [])
    if any(k in REMOVE for k in top):
        data["env_var_keys"] = [k for k in top if k not in REMOVE]
        changed = True

    if changed:
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Patched IPFS file: {f.name}")
        patched_files += 1

    if full_meta is None:
        full_meta = data  # keep the most recent match as template for DB fix

print(f"\nTotal IPFS files patched: {patched_files}")

# ── 2. Fix DB identity_metadata ───────────────────────────────────────────────
if full_meta is None:
    print("ERROR: No IPFS file found for researcher-01 — DB not fixed")
else:
    # Ensure env_var_keys are clean in the template
    full_meta["env_var_keys"] = KEEP
    if "capabilities" in full_meta:
        full_meta["capabilities"]["env_var_keys"] = KEEP
    if "sandbox_config" in full_meta:
        full_meta["sandbox_config"]["env_var_keys"] = KEEP

    conn = sqlite3.connect(str(DB))
    conn.execute(
        "UPDATE agents SET identity_metadata = ? WHERE agent_id = ?",
        (json.dumps(full_meta), AGENT_ID),
    )
    conn.commit()
    conn.close()
    print(f"DB identity_metadata fixed for {AGENT_ID}")

print("\nRestart the backend now.")

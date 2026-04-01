from __future__ import annotations
import logging
import sqlite3
from pathlib import Path
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

DB_PATH = Path(settings.storage_path) / "agentmarket.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id         TEXT PRIMARY KEY,
            registration_id  TEXT NOT NULL,
            token_id         INTEGER,
            tx_hash          TEXT,
            docker_image     TEXT,
            status           TEXT NOT NULL DEFAULT 'active',
            registered_at    TEXT,
            owner_address    TEXT DEFAULT ''
        )
    """)
    # Ajouter la colonne si elle n'existe pas (migration)
    try:
        conn.execute("ALTER TABLE agents ADD COLUMN owner_address TEXT DEFAULT ''")
        conn.commit()
        logger.info("Colonne owner_address ajoutee")
    except Exception:
        pass  # Colonne existe deja
    conn.commit()
    conn.close()
    logger.info("DB initialisee: %s", DB_PATH)
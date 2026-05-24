"""
migrate_sqlite_to_postgres.py
Transfère les 5 tables runtime de SQLite vers Postgres.
Lance une seule fois : python migrate_sqlite_to_postgres.py
"""
import sqlite3
import sys
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

SQLITE_PATH  = r"C:\tmp\agentmarket\agentmarket.db"
POSTGRES_URL = None  # lu depuis .env automatiquement


def get_postgres_engine():
    import os, pathlib
    env_file = pathlib.Path(__file__).parent.parent / ".env"
    db_url = None
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                db_url = line.split("=", 1)[1].strip()
                break
    if not db_url:
        print("ERROR: DATABASE_URL non trouvé dans .env")
        sys.exit(1)
    return sa.create_engine(db_url)


def sqlite_rows(conn, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table}")
    return [dict(row) for row in cur.fetchall()]


def transfer(pg_engine, rows: list[dict], table: str, pk: str) -> int:
    if not rows:
        print(f"  {table}: 0 lignes — rien à transférer")
        return 0
    meta = sa.MetaData()
    meta.reflect(bind=pg_engine, only=[table])
    tbl  = meta.tables[table]
    transferred = 0
    with pg_engine.begin() as conn:
        for row in rows:
            stmt = pg_insert(tbl).values(**row).on_conflict_do_update(
                index_elements=[pk],
                set_={k: row[k] for k in row if k != pk}
            )
            conn.execute(stmt)
            transferred += 1
    return transferred


def main():
    print(f"=== Migration SQLite vers Postgres ({datetime.now(timezone.utc).strftime('%H:%M:%S')}) ===\n")

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_engine   = get_postgres_engine()

    tables = [
        ("agent_telemetry",    "agent_id"),
        ("judge_verdicts",     "id"),
        ("access_grants",      "id"),
        ("pipeline_tasks",     "id"),
        ("validation_sessions","agent_id"),
    ]

    total = 0
    for table, pk in tables:
        print(f">> {table}")
        rows = sqlite_rows(sqlite_conn, table)
        print(f"  SQLite: {len(rows)} lignes")
        n = transfer(pg_engine, rows, table, pk)
        print(f"  Postgres: {n} lignes transferees OK")
        total += n

    sqlite_conn.close()
    print(f"\n=== Terminé — {total} lignes transférées au total ===")


if __name__ == "__main__":
    main()

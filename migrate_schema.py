import os
import sqlite3
from pathlib import Path


def resolve_db_path() -> str:
    env = os.environ.get("DB_PATH", "").strip()
    if env:
        # Tillad både absolute og relative paths
        if os.path.isabs(env):
            return env
        return os.path.abspath(os.path.join(os.path.dirname(__file__), env))

    base = os.path.dirname(__file__)
    candidates = [
        os.path.join(base, "data", "database.sqlite3"),
        os.path.join(base, "database.sqlite3"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    return candidates[0]


DB_PATH = resolve_db_path()


def column_exists(cur, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == col for row in cur.fetchall())


def add_column_if_missing(cur, table: str, col_def: str):
    col_name = col_def.split()[0]
    if column_exists(cur, table, col_name):
        print(f"✓ Kolonne findes allerede: {table}.{col_name}")
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
    print(f"+ Tilføjede kolonne: {table}.{col_name}")


def main():
    # Sørg for db folder findes
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Existing migrations (bevar dine nuværende)
    add_column_if_missing(cur, "signups", "approved_work_hours REAL")
    add_column_if_missing(cur, "signups", "hours_approved_by_admin INTEGER DEFAULT 0")
    add_column_if_missing(cur, "signups", "freelancer_note TEXT")
    add_column_if_missing(cur, "shifts", "admin_note TEXT")


    # Ny tabel: extra_shifts
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS extra_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL,

            date TEXT NOT NULL,          -- 'YYYY-MM-DD'
            work_start TEXT NOT NULL,    -- 'HH:MM'
            work_end TEXT NOT NULL,      -- 'HH:MM'
            work_hours REAL NOT NULL,    -- beregnet

            note TEXT,                   -- fri tekst til admin
            status TEXT NOT NULL DEFAULT 'REQUESTED',  -- REQUESTED/APPROVED/REJECTED

            approved_work_hours REAL,
            hours_approved_by_admin INTEGER DEFAULT 0,

            payroll_paid INTEGER DEFAULT 0,
            payroll_paid_at TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(person_id) REFERENCES persons(id)
        )
        """
    )
    print("✓ Tabel sikret: extra_shifts")

    conn.commit()

    print("\nAktuelle kolonner i signups:")
    cur.execute("PRAGMA table_info(signups)")
    for row in cur.fetchall():
        print(f"- {row[1]} ({row[2]}) default={row[4]}")

    print("\nAktuelle kolonner i extra_shifts:")
    cur.execute("PRAGMA table_info(extra_shifts)")
    for row in cur.fetchall():
        print(f"- {row[1]} ({row[2]}) default={row[4]}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()

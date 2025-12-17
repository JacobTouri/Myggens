import sqlite3

DB_PATH = r"C:\Users\jthel\OneDrive - Aalborg Universitet\Desktop\myggen_vagtplan\data\database.sqlite3"

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
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    add_column_if_missing(cur, "signups", "approved_work_hours REAL")
    add_column_if_missing(cur, "signups", "hours_approved_by_admin INTEGER DEFAULT 0")

    conn.commit()

    print("\nAktuelle kolonner i signups:")
    cur.execute("PRAGMA table_info(signups)")
    for row in cur.fetchall():
        # row: (cid, name, type, notnull, dflt_value, pk)
        print(f"- {row[1]} ({row[2]}) default={row[4]}")

    conn.close()
    print("\nDone.")

if __name__ == "__main__":
    main()

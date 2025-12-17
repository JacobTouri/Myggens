import os
import sqlite3
from datetime import date

# Status-konstanter
STATUS_REQUESTED = "REQUESTED"
STATUS_APPROVED = "APPROVED"
STATUS_RELEASE_REQUESTED = "RELEASE_REQUESTED"
STATUS_CANCELLED_BY_ADMIN = "CANCELLED_BY_ADMIN"

# Sti til databasen (forventer en undermappe "data" med database.sqlite3)
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "database.sqlite3")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

print("DB PATH:", os.path.abspath(DB_PATH))

def init_db():
    """Opret tabeller, hvis de ikke findes, og seed nogle dummy-shifts."""
    conn = get_connection()
    cur = conn.cursor()

    # Freelancere
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS persons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Vagter
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,          -- fx '2025-11-21'
            start_time TEXT NOT NULL,    -- fx '17:00'
            location TEXT NOT NULL,      -- Hvor 
            description TEXT,            -- ekstra fritekst
            customer TEXT,               -- Hvem
            event_type TEXT,             -- Hvad
            guest_count INTEGER,         -- Antal gæster
            required_staff INTEGER NOT NULL,  -- bemanding (antal medarbejdere)
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


        # Tilmeldinger
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS signups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL,
            shift_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            available_from TEXT,
            meet_time TEXT,

            work_start TEXT,
            work_end TEXT,
            work_hours REAL,

            -- NYT: løn/afregning
            payroll_paid INTEGER DEFAULT 0,      -- 0 = ikke afregnet, 1 = afregnet
            payroll_paid_at TEXT,                -- hvornår den blev markeret som afregnet

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(person_id, shift_id),
            FOREIGN KEY(person_id) REFERENCES persons(id),
            FOREIGN KEY(shift_id) REFERENCES shifts(id)
        )
        """
    )



    conn.commit()

    # Seed nogle standard-shifts første gang
    cur.execute("SELECT COUNT(*) AS c FROM shifts")
    row = cur.fetchone()
    if row["c"] == 0:
        cur.executemany(
            """
            INSERT INTO shifts (date, start_time, location, description, required_staff)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("2025-11-21", "17:00", "Munken", "Teambuilding – 50 pers.", 3),
                ("2025-11-22", "16:30", "Munken", "Pizza teambuilding – 40 pers.", 4),
                ("2025-11-23", "18:00", "AA", "Julefrokost – 80 pers.", 5),
            ],
        )
        conn.commit()

    conn.close()


def _shift_row_to_dict(
    row,
    approved_count: int = 0,
    requested_count: int = 0,
    release_requested_count: int = 0,
):
    """Mapper en DB-row til det format, dine templates bruger."""
    pending = requested_count + release_requested_count

    return {
        "id": row["id"],
        "date": row["date"],
        "time": row["start_time"],
        "location": row["location"],
        "description": row["description"],
        # Nye felter hvis du har lavet dem i shifts-tabellen:
        "customer": row["customer"] if "customer" in row.keys() else None,
        "event_type": row["event_type"] if "event_type" in row.keys() else None,
        "guest_count": row["guest_count"] if "guest_count" in row.keys() else None,
        # Bemanding
        "needed": row["required_staff"],
        "approved": approved_count,
        # Pending-ting til admin-dashboard
        "pending": pending,
        "pending_signups": requested_count,
        "pending_releases": release_requested_count,
        "is_active": row["is_active"],
    }





def get_all_shifts():
    """Hent alle aktive vagter + antal APPROVED tilmeldinger."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.*,
            COALESCE(SUM(CASE WHEN sg.status = ? THEN 1 ELSE 0 END), 0) AS approved_count
        FROM shifts s
        LEFT JOIN signups sg ON sg.shift_id = s.id
        WHERE s.is_active = 1
        GROUP BY s.id
        ORDER BY s.date, s.start_time
        """,
        (STATUS_APPROVED,),
    )
    rows = cur.fetchall()
    conn.close()
    return [_shift_row_to_dict(row, row["approved_count"]) for row in rows]


def get_shift(shift_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.*,
            COALESCE(SUM(CASE WHEN sg.status = ? THEN 1 ELSE 0 END), 0) AS approved_count
        FROM shifts s
        LEFT JOIN signups sg ON sg.shift_id = s.id
        WHERE s.id = ?
        GROUP BY s.id
        """,
        (STATUS_APPROVED, shift_id),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return _shift_row_to_dict(row, row["approved_count"])

def create_shift(
    date: str,
    start_time: str,
    location: str,
    description: str,
    required_staff: int,
    customer: str | None = None,
    event_type: str | None = None,
    guest_count: int | None = None,
):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO shifts (
            date, start_time, location, description,
            required_staff, customer, event_type, guest_count, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (date, start_time, location, description,
         required_staff, customer, event_type, guest_count),
    )
    conn.commit()
    conn.close()


def update_shift(
    shift_id: int,
    date: str,
    start_time: str,
    location: str,
    description: str,
    required_staff: int,
    customer: str | None = None,
    event_type: str | None = None,
    guest_count: int | None = None,
):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE shifts
        SET date = ?, start_time = ?, location = ?, description = ?,
            required_staff = ?, customer = ?, event_type = ?, guest_count = ?
        WHERE id = ?
        """,
        (
            date, start_time, location, description,
            required_staff, customer, event_type, guest_count, shift_id,
        ),
    )
    conn.commit()
    conn.close()


def get_all_shifts_admin():
    """Hent alle vagter (aktive + arkiverede) med approved- og pending-counts."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.*,
            COALESCE(SUM(CASE WHEN sg.status = ? THEN 1 ELSE 0 END), 0) AS approved_count,
            COALESCE(SUM(CASE WHEN sg.status = ? THEN 1 ELSE 0 END), 0) AS requested_count,
            COALESCE(SUM(CASE WHEN sg.status = ? THEN 1 ELSE 0 END), 0) AS release_requested_count
        FROM shifts s
        LEFT JOIN signups sg ON sg.shift_id = s.id
        GROUP BY s.id
        ORDER BY s.date, s.start_time
        """,
        (
            STATUS_APPROVED,
            STATUS_REQUESTED,
            STATUS_RELEASE_REQUESTED,
        ),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        _shift_row_to_dict(
            row,
            row["approved_count"],
            row["requested_count"],
            row["release_requested_count"],
        )
        for row in rows
    ]

def get_historic_shifts():
    """
    Hent alle vagter i historikken (is_active = -1)
    med approved-count, så vi kan genbruge _shift_row_to_dict.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.*,
            COALESCE(SUM(CASE WHEN sg.status = ? THEN 1 ELSE 0 END), 0) AS approved_count
        FROM shifts s
        LEFT JOIN signups sg ON sg.shift_id = s.id
        WHERE s.is_active = -1
        GROUP BY s.id
        ORDER BY s.date DESC, s.start_time DESC
        """,
        (STATUS_APPROVED,),
    )
    rows = cur.fetchall()
    conn.close()
    return [_shift_row_to_dict(row, row["approved_count"]) for row in rows]




def get_or_create_person(name: str, phone: str) -> int:
    """Find person via telefon, eller opret ny."""
    phone_clean = phone.replace(" ", "")
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM persons WHERE phone = ?", (phone_clean,))
    row = cur.fetchone()
    if row:
        # Hvis navnet er ændret, opdater det
        if name and row["name"] != name:
            cur.execute(
                "UPDATE persons SET name = ? WHERE id = ?",
                (name, row["id"]),
            )
            conn.commit()
        person_id = row["id"]
    else:
        cur.execute(
            "INSERT INTO persons (name, phone) VALUES (?, ?)",
            (name, phone_clean),
        )
        conn.commit()
        person_id = cur.lastrowid

    conn.close()
    return person_id


def create_signup(
    shift_id: int,
    name: str,
    phone: str,
    initial_status: str = STATUS_REQUESTED,
    available_from: str | None = None,
):
    """Opret en tilmelding. Returnerer signup_id eller None hvis den allerede findes."""
    person_id = get_or_create_person(name, phone)
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO signups (person_id, shift_id, status, available_from)
            VALUES (?, ?, ?, ?)
            """,
            (person_id, shift_id, initial_status, available_from),
        )
        conn.commit()
        signup_id = cur.lastrowid
    except sqlite3.IntegrityError:
        # UNIQUE(person_id, shift_id) – allerede tilmeldt
        signup_id = None

    conn.close()
    return signup_id


def get_signups_by_phone(phone: str):
    """Hent alle tilmeldinger for et telefonnummer, inkl. shift-info."""
    phone_clean = phone.replace(" ", "")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            sg.id AS signup_id,
            sg.status AS status,
            sg.available_from AS available_from,
            sg.meet_time AS meet_time,
            sg.work_start AS work_start,
            sg.work_end AS work_end,
            sg.work_hours AS work_hours,
            s.id AS shift_id,
            s.date,
            s.start_time,
            s.location,
            s.description,
            s.required_staff
        FROM signups sg
        JOIN persons p ON p.id = sg.person_id
        JOIN shifts s ON s.id = sg.shift_id
        WHERE p.phone = ?
        ORDER BY s.date, s.start_time
        """,
        (phone_clean,),
    )
    rows = cur.fetchall()
    conn.close()

    result = []
    for row in rows:
        shift_dict = {
            "id": row["shift_id"],
            "date": row["date"],
            "time": row["start_time"],
            "location": row["location"],
            "description": row["description"],
            "needed": row["required_staff"],
        }
        result.append(
            {
                "signup_id": row["signup_id"],
                "status": row["status"],
                "available_from": row["available_from"],
                "meet_time": row["meet_time"],
                "work_start": row["work_start"],
                "work_end": row["work_end"],
                "work_hours": row["work_hours"],
                "shift": shift_dict,
            }
        )
    return result



def get_signup(signup_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            sg.id AS signup_id,
            sg.status AS status,
            sg.available_from AS available_from,
            sg.meet_time AS meet_time,
            sg.work_start AS work_start,
            sg.work_end AS work_end,
            sg.work_hours AS work_hours,
            p.phone AS phone,
            sg.shift_id AS shift_id
        FROM signups sg
        JOIN persons p ON p.id = sg.person_id
        WHERE sg.id = ?
        """,
        (signup_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)

def set_signup_worked_hours(signup_id: int,
                            work_start: str | None,
                            work_end: str | None,
                            work_hours: float | None):
    """Gem registreret arbejdstid på en tilmelding."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE signups SET work_start = ?, work_end = ?, work_hours = ? WHERE id = ?",
        (work_start, work_end, work_hours, signup_id),
    )
    conn.commit()
    conn.close()

def set_signup_status(signup_id: int, new_status: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE signups SET status = ? WHERE id = ?",
        (new_status, signup_id),
    )
    conn.commit()
    conn.close()

def set_shift_state(shift_id: int, state: int):
    """
    Sæt en vagt til:
    1  = aktiv (vises i 'Aktive vagter')
    0  = arkiveret (vises i 'Arkiverede vagter')
    -1 = historik (vises ikke i dashboardet)
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE shifts SET is_active = ? WHERE id = ?",
        (state, shift_id),
    )
    conn.commit()
    conn.close()


def set_shift_active(shift_id: int, is_active: bool):
    """
    Bagudkompatibel helper:
    True  -> aktiv (1)
    False -> arkiveret (0)
    """
    set_shift_state(shift_id, 1 if is_active else 0)

def sink_all_archived_shifts():
    """
    Flyt alle arkiverede vagter (is_active = 0) til historik (is_active = -1).
    Bruges fra admin-dashboardet.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE shifts SET is_active = -1 WHERE is_active = 0"
    )
    conn.commit()
    conn.close()

def revive_historic_shift(shift_id: int):
    """Flyt en historik-vagt (is_active=-1) tilbage til arkiv (is_active=0)."""
    set_shift_state(shift_id, 0)


def delete_shift_permanently(shift_id: int):
    """Slet en vagt fuldstændigt fra databasen (inkl. alle tilmeldinger)."""
    conn = get_connection()
    cur = conn.cursor()

    # Slet tilmeldinger først (pga foreign keys)
    cur.execute("DELETE FROM signups WHERE shift_id = ?", (shift_id,))
    # Slet selve vagten
    cur.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))

    conn.commit()
    conn.close()

def set_signup_payroll_status(signup_id: int, paid: bool):
    """
    Sæt/ryd 'afregnet' på en signup.
    paid=True  -> marker som afregnet + timestamp
    paid=False -> nulstil afregning
    """
    conn = get_connection()
    cur = conn.cursor()

    if paid:
        cur.execute("""
            UPDATE signups
            SET payroll_paid = 1,
                payroll_paid_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (signup_id,))
    else:
        cur.execute("""
            UPDATE signups
            SET payroll_paid = 0,
                payroll_paid_at = NULL
            WHERE id = ?
        """, (signup_id,))

    conn.commit()
    conn.close()


def get_signups_for_shift(shift_id: int):
    """
    Hent alle aktive tilmeldinger til en given vagt, inkl. person-oplysninger.
    Filtrerer automatisk CANCELLED_BY_ADMIN fra admin-visningen.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            sg.id AS signup_id,
            sg.status AS status,
            sg.available_from AS available_from,
            sg.meet_time AS meet_time,
            p.name AS person_name,
            p.phone AS phone
        FROM signups sg
        JOIN persons p ON p.id = sg.person_id
        WHERE sg.shift_id = ?
          AND sg.status != ?
        ORDER BY sg.created_at
        """,
        (shift_id, STATUS_CANCELLED_BY_ADMIN),
    )

    rows = cur.fetchall()
    conn.close()

    signups = []
    for row in rows:
        signups.append(
            {
                "signup_id": row["signup_id"],
                "status": row["status"],
                "available_from": row["available_from"],
                "meet_time": row["meet_time"],
                "name": row["person_name"],
                "phone": row["phone"],
            }
        )

    return signups

def get_signups_for_shift_with_hours(shift_id: int):
    """
    Hent alle tilmeldinger til en given vagt, inkl. person-info
    og registrerede arbejdstimer / afregningsstatus.
    Bruges i admin-historik.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            sg.id AS signup_id,
            sg.status AS status,
            sg.available_from AS available_from,
            sg.meet_time AS meet_time,
            sg.work_start AS work_start,
            sg.work_end AS work_end,
            sg.work_hours AS work_hours,
            sg.payroll_paid AS payroll_paid,
            sg.payroll_paid_at AS payroll_paid_at,
            p.name AS person_name,
            p.phone AS phone
        FROM signups sg
        JOIN persons p ON p.id = sg.person_id
        WHERE sg.shift_id = ?
        ORDER BY p.name
        """,
        (shift_id,),
    )
    rows = cur.fetchall()
    conn.close()

    signups = []
    for row in rows:
        signups.append(
            {
                "signup_id": row["signup_id"],
                "status": row["status"],
                "available_from": row["available_from"],
                "meet_time": row["meet_time"],
                "work_start": row["work_start"],
                "work_end": row["work_end"],
                "work_hours": row["work_hours"],
                "payroll_paid": bool(row["payroll_paid"]) if row["payroll_paid"] is not None else False,
                "payroll_paid_at": row["payroll_paid_at"],
                "name": row["person_name"],
                "phone": row["phone"],
            }
        )

    return signups



def sink_all_archived():
    """
    Sætter alle arkiverede vagter (is_active = 0)
    til historik/sink (is_active = -1).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE shifts SET is_active = -1 WHERE is_active = 0"
    )
    conn.commit()
    conn.close()

def set_signup_meet_time(signup_id: int, meet_time: str | None):
    """Sæt eller nulstil mødetid for en tilmelding."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE signups SET meet_time = ? WHERE id = ?",
        (meet_time, signup_id),
    )
    conn.commit()
    conn.close()

from datetime import date

def get_hours_for_month(year: int, month: int, include_paid: bool = False, include_missing: bool = True):
    conn = get_connection()
    cur = conn.cursor()

    year_str = f"{year:04d}"
    month_str = f"{month:02d}"
    today_str = date.today().strftime("%Y-%m-%d")

    base_query = """
        SELECT
            sg.id AS signup_id,
            sg.work_start,
            sg.work_end,
            sg.work_hours,
            sg.approved_work_hours,
            sg.hours_approved_by_admin,
            sg.payroll_paid,
            sg.payroll_paid_at,
            s.date AS shift_date,
            s.location,
            s.description,
            p.name AS person_name,
            p.phone AS phone
        FROM signups sg
        JOIN shifts s ON s.id = sg.shift_id
        JOIN persons p ON p.id = sg.person_id
    """

    conditions = [
        "sg.status = ?",
        "substr(s.date, 1, 4) = ?",
        "substr(s.date, 6, 2) = ?",
        "s.date <= ?",
    ]
    params = [STATUS_APPROVED, year_str, month_str, today_str]

    if not include_missing:
        conditions.append("sg.work_hours IS NOT NULL")

    if not include_paid:
        conditions.append("(sg.payroll_paid IS NULL OR sg.payroll_paid = 0)")

    query = base_query + " WHERE " + " AND ".join(conditions) + " ORDER BY p.name, s.date"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "signup_id": row["signup_id"],
            "work_start": row["work_start"],
            "work_end": row["work_end"],
            "work_hours": row["work_hours"],
            "approved_work_hours": row["approved_work_hours"],
            "hours_approved_by_admin": bool(row["hours_approved_by_admin"]),
            "payroll_paid": bool(row["payroll_paid"]),
            "payroll_paid_at": row["payroll_paid_at"],
            "shift_date": row["shift_date"],
            "location": row["location"],
            "description": row["description"],
            "person_name": row["person_name"],
            "phone": row["phone"],
        })
    return result




def get_pending_admin_actions():
    """
    Returnér hvor mange åbne handlinger admin har:
    - pending_signups: nye tilmeldinger (REQUESTED)
    - pending_releases: ønsket fri (RELEASE_REQUESTED)
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = ? THEN 1 ELSE 0 END), 0) AS pending_signups,
            COALESCE(SUM(CASE WHEN status = ? THEN 1 ELSE 0 END), 0) AS pending_releases
        FROM signups
        """,
        (STATUS_REQUESTED, STATUS_RELEASE_REQUESTED),
    )
    row = cur.fetchone()
    conn.close()

    pending_signups = row["pending_signups"]
    pending_releases = row["pending_releases"]
    return {
        "pending_signups": pending_signups,
        "pending_releases": pending_releases,
        "pending_total": pending_signups + pending_releases,
    }


def delete_signup(signup_id: int):
    """Slet en tilmelding helt fra databasen."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM signups WHERE id = ?",
        (signup_id,),
    )
    conn.commit()
    conn.close()


def get_all_persons():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, phone, created_at FROM persons ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def approve_work_hours(signup_id: int, approved_hours: float):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE signups
        SET approved_work_hours = ?,
            hours_approved_by_admin = 1
        WHERE id = ?
    """, (approved_hours, signup_id))

    conn.commit()
    conn.close()

def get_person(person_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, phone, created_at FROM persons WHERE id = ?",
        (person_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_signups_for_person(person_id: int):
    """
    Hent alle tilmeldinger for en given person, sammen med vagternes info.
    Vi filtrerer CANCELLED_BY_ADMIN fra, så kun reelle vagter vises.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            sg.id AS signup_id,
            sg.status AS status,
            sg.available_from AS available_from,
            sg.meet_time AS meet_time,
            s.id AS shift_id,
            s.date AS date,
            s.start_time AS start_time,
            s.location AS location,
            s.description AS description
        FROM signups sg
        JOIN shifts s ON s.id = sg.shift_id
        WHERE sg.person_id = ?
          AND sg.status != ?
        ORDER BY s.date, s.start_time
        """,
        (person_id, STATUS_CANCELLED_BY_ADMIN),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_signup_by_id(signup_id: int):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            sg.id,
            sg.shift_id,
            sg.person_id,
            sg.status,
            sg.work_start,
            sg.work_end,
            sg.work_hours,
            sg.approved_work_hours,
            sg.hours_approved_by_admin,
            sg.payroll_paid,
            sg.payroll_paid_at
        FROM signups sg
        WHERE sg.id = ?
    """, (signup_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    # row er sqlite Row (dict-like) hvis du har row_factory
    return dict(row)


def delete_person(person_id: int):
    """
    Sletter en person og alle deres tilmeldinger.
    Bruges kun fra admin-siden.
    """
    conn = get_connection()
    cur = conn.cursor()
    # Først signups, så personen (pga. foreign key)
    cur.execute("DELETE FROM signups WHERE person_id = ?", (person_id,))
    cur.execute("DELETE FROM persons WHERE id = ?", (person_id,))
    conn.commit()
    conn.close()


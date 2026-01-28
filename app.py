import os
import secrets
from functools import wraps
from datetime import date, datetime, timedelta

from flask import (
    Flask,
    render_template,
    request,
    abort,
    redirect,
    url_for,
    jsonify,
    session,
    flash,
)

import database
from database import (
    STATUS_REQUESTED,
    STATUS_APPROVED,
    STATUS_RELEASE_REQUESTED,
    STATUS_CANCELLED_BY_ADMIN,
)

app = Flask(__name__)

# ============================
# Produktion: secrets skal komme fra ENV
# ============================
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

if not SECRET_KEY:
    # Lokalt: generér en midlertidig key (så du ikke bliver blokeret i dev)
    # Produktion: sæt SECRET_KEY i platformens "Secrets".
    SECRET_KEY = secrets.token_hex(32)
    print("⚠️  SECRET_KEY mangler. Kører med en midlertidig nøgle (sessions nulstilles ved restart).")

if not ADMIN_PASSWORD:
    # Lokalt fallback, men i produktion SKAL du sætte ADMIN_PASSWORD.
    ADMIN_PASSWORD = "Myggens"
    print("⚠️  ADMIN_PASSWORD mangler. Fallback til standard (skift i produktion!).")

app.secret_key = SECRET_KEY

# Cookies: sikre defaults. Secure bliver automatisk OK bag HTTPS.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


# Secret key til session (brug evt. noget mere hemmeligt i produktion)
app.secret_key = "skift-mig-til-noget-hemmeligt"

database.init_db()

@app.context_processor
def inject_now():
    return {"now": datetime.now}

@app.context_processor
def inject_admin_notifications():
    """
    Gør pending-antal tilgængeligt i templates som:
    - pending_total
    - pending_signups
    - pending_releases
    """
    if not session.get("is_admin"):
        return {}

    pending = database.get_pending_admin_actions()
    return {
        "pending_total": pending["pending_total"],
        "pending_signups": pending["pending_signups"],
        "pending_releases": pending["pending_releases"],
    }

from datetime import datetime

@app.template_filter("dkdate")
def dkdate(value):
    """Konverterer ISO 'YYYY-MM-DD' til dansk 'DD-MM-YYYY'."""
    if not value:
        return ""
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
        return d.strftime("%d-%m-%Y")
    except Exception:
        return value



def parse_danish_date(d: str) -> str | None:
    """
    Accepterer fx:
    - '21-12-2025'
    - '21/12/2025'
    - '21.12.2025'
    - '2025-12-21'
    og returnerer ISO 'YYYY-MM-DD' eller None ved fejl.
    """
    if not d:
        return None

    cleaned = d.strip().replace("/", "-").replace(".", "-")

    # Først prøver vi dansk format
    try:
        return datetime.strptime(cleaned, "%d-%m-%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Så prøver vi ISO
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None

def format_danish_date(date_iso: str) -> str:
    """Konverterer '2025-12-11' → '11-12-2025'."""
    try:
        parts = date_iso.split("-")
        if len(parts) != 3:
            return date_iso
        year, month, day = parts
        return f"{day}-{month}-{year}"
    except:
        return date_iso



# =====================================================
# Admin helper: kun adgang hvis man er logget ind som admin
# =====================================================
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return wrapper

def freelancer_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("freelancer_person_id"):
            return redirect(url_for("freelancer_login"))
        return f(*args, **kwargs)
    return wrapper


# ============================
# Offentlige sider (freelancer)
# ============================

@app.route("/")
def landing():
    # Hvis man allerede er logget ind, skal man ikke se gatewayen
    if session.get("freelancer_person_id"):
        return redirect(url_for("vagtoversigt"))
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    return render_template("landing.html")



@app.route("/vagter")
@freelancer_required
def vagtoversigt():
    shifts = database.get_all_shifts()
    today_str = date.today().isoformat()  # fx '2025-12-10'
    future_shifts = [s for s in shifts if s["date"] >= today_str]
    return render_template("index.html", shifts=future_shifts)

@app.get("/vagtoversigt/mogens")
@freelancer_required
def vagtoversigt_mogens():
    shifts = database.get_all_shifts()  # ✅ VIGTIGT: med ()
    return render_template("index_mogens.html", shifts=shifts)




@app.route("/tilmeld/<int:shift_id>", methods=["GET", "POST"])
@freelancer_required
def tilmeld(shift_id):
    shift = database.get_shift(shift_id)
    if shift is None:
        abort(404)

    message = None
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone_raw = request.form.get("phone", "").strip()

        # Note til admin (valgfri)
        freelancer_note = request.form.get("freelancer_note", "").strip()
        freelancer_note_value = freelancer_note if freelancer_note else None

        availability_type = request.form.get("availability_type", "any").strip()
        available_from = request.form.get("available_from", "").strip()    # 'HH:MM' eller ""
        available_until = request.form.get("available_until", "").strip()  # 'HH:MM' eller ""

        # Normalisér telefon (fjern mellemrum)
        phone = phone_raw.replace(" ", "")

        # Basic validering
        if not name or not phone:
            error = "Udfyld både navn og telefon."
        elif not phone.isdigit() or len(phone) < 6:
            error = "Tjek dit telefonnummer – det ser forkert ud."
        else:
            # Normalisér til None hvis tom
            available_from_value = available_from if available_from else None
            available_until_value = available_until if available_until else None

            # Availability-validering
            if availability_type == "any":
                available_from_value = None
                available_until_value = None

            elif availability_type == "from":
                available_until_value = None
                if not available_from_value:
                    error = "Vælg et tidspunkt, hvis du ikke kan hele dagen."

            elif availability_type == "until":
                available_from_value = None
                if not available_until_value:
                    error = "Vælg et tidspunkt, hvis du kun kan til et bestemt tidspunkt."

            elif availability_type == "range":
                if not available_from_value or not available_until_value:
                    error = "Vælg både start og slut, hvis du vælger et tidsrum."
                else:
                    # 'HH:MM' kan sammenlignes som strings
                    if available_from_value >= available_until_value:
                        error = "Sluttid skal være efter starttid."

            else:
                # Ukendt type → fallback
                available_from_value = None
                available_until_value = None

            if not error:
                signup_id = database.create_signup(
                    shift_id=shift_id,
                    name=name,
                    phone=phone,
                    initial_status=STATUS_REQUESTED,
                    available_from=available_from_value,
                    available_until=available_until_value,
                    freelancer_note=freelancer_note_value,
                )

                if signup_id is None:
                    error = "Du er allerede tilmeldt denne vagt."
                else:
                    print(
                        "NY TILMELDING:",
                        signup_id,
                        shift_id,
                        name,
                        phone,
                        availability_type,
                        available_from_value,
                        available_until_value,
                        freelancer_note_value,
                    )
                    message = "Din tilmelding er modtaget!"

    return render_template("tilmeld.html", shift=shift, message=message, error=error)


@app.route("/freelancer/frameld/<int:signup_id>", methods=["POST"])
@freelancer_required
def freelancer_frameld(signup_id: int):
    phone = (session.get("freelancer_phone") or "").strip()
    if not phone:
        abort(403)

    signup = database.get_signup_by_id(signup_id)
    if signup is None:
        abort(404)

    # ownership check
    if str(signup.get("phone") or "").strip() != phone:
        abort(403)

    ok = database.cancel_signup_request(signup_id)
    if ok:
        flash("Du er frameldt vagten.", "success")
    else:
        flash("Kan ikke framelde: tilmeldingen er allerede behandlet.", "error")
    return redirect(url_for("mine_vagter"))

@app.route("/freelancer/login", methods=["GET", "POST"])
def freelancer_login():
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name or not phone:
            error = "Udfyld både navn og telefonnummer."
        elif not phone.replace(" ", "").isdigit():
            error = "Telefonnummer skal være tal."
        else:
            # Opret eller find personen i databasen
            person_id = database.get_or_create_person(name, phone)

            # Læg det i session
            session["freelancer_person_id"] = person_id
            session["freelancer_name"] = name
            session["freelancer_phone"] = phone.replace(" ", "")

            flash("Du er nu logget ind som freelancer hos Myggens")
            return redirect(url_for("vagtoversigt"))

    return render_template("freelancer_login.html", error=error)

def _parse_hhmm(value: str) -> int | None:
    """Returnerer minutter siden midnat for 'HH:MM' ellers None."""
    if not value:
        return None
    value = value.strip()
    try:
        parts = value.split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if h < 0 or h > 23 or m < 0 or m > 59:
            return None
        return h * 60 + m
    except ValueError:
        return None


@app.route("/ekstravagt", methods=["GET", "POST"])
@freelancer_required
def freelancer_extra_shift():
    message = None
    error = None

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()

        date_str = (request.form.get("date") or "").strip()          # forvent: YYYY-MM-DD
        work_start = (request.form.get("work_start") or "").strip()  # HH:MM
        work_end = (request.form.get("work_end") or "").strip()      # HH:MM
        note = (request.form.get("note") or "").strip()

        # ---- basic validation ----
        if not name or not phone:
            error = "Udfyld navn og telefonnummer."
        elif not phone.replace(" ", "").isdigit() or len(phone.replace(" ", "")) < 6:
            error = "Tjek telefonnummer – det ser forkert ud."
        else:
            # valider datoformat
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                error = "Dato skal være i formatet YYYY-MM-DD."

        # valider tid + beregn work_hours
        if not error:
            start_min = _parse_hhmm(work_start)
            end_min = _parse_hhmm(work_end)

            if start_min is None or end_min is None:
                error = "Start og slut skal være i formatet HH:MM."
            elif end_min <= start_min:
                error = "Sluttid skal være efter starttid."
            else:
                work_hours = round((end_min - start_min) / 60.0, 2)
                if work_hours <= 0 or work_hours > 24:
                    error = "Timer ser ikke rigtige ud."

        if not error:
            # ---- save ----
            database.create_extra_shift(
                name=name,
                phone=phone,
                date_str=date_str,
                work_start=work_start,
                work_end=work_end,
                work_hours=work_hours,
                note=note,
            )
            message = "Ekstravagt sendt til admin ✅"

    return render_template("extra_shift.html", message=message, error=error)



@app.route("/freelancer/logout")
def freelancer_logout():
    session.pop("freelancer_person_id", None)
    session.pop("freelancer_name", None)
    session.pop("freelancer_phone", None)
    flash("Du er logget ud.")
    return redirect(url_for("freelancer_login"))

@app.route("/admin/personer")
@admin_required
def admin_person_list():
    persons = database.get_all_persons()
    return render_template("admin_person_list.html", persons=persons)

@app.route("/admin/personer/<int:person_id>")
@admin_required
def admin_person_detail(person_id):
    person = database.get_person(person_id)
    if not person:
        abort(404)

    signups = database.get_signups_for_person(person_id)
    return render_template(
        "admin_person_detail.html",
        person=person,
        signups=signups,
    )


@app.post("/admin/personer/<int:person_id>/delete")
@admin_required
def admin_person_delete(person_id):
    database.delete_person(person_id)
    flash("Personen er fjernet fra kartoteket.")
    return redirect(url_for("admin_person_list"))


@app.route("/mine-vagter", methods=["GET", "POST"])
@freelancer_required
def mine_vagter():
    # Default: brug telefonnummeret fra session
    phone = session.get("freelancer_phone", "")

    # Tillad override via form eller query (samme som før)
    if request.method == "POST":
        phone = request.form.get("phone", "").strip() or phone
    else:
        phone = request.args.get("phone", "").strip() or phone

    upcoming_signups = []
    unlogged_signups = []
    has_any_signups = False

    if phone:
        all_signups = database.get_signups_by_phone(phone)
        has_any_signups = bool(all_signups)

        today_str = date.today().isoformat()
        phone_clean = phone.replace(" ", "")

        # Kommende vagter
        upcoming_signups = [
            item for item in all_signups
            if item["shift"]["date"] >= today_str
            and item["status"] != STATUS_CANCELLED_BY_ADMIN
        ]

        # Tidligere vagter hvor man var godkendt
        past_approved = [
            item for item in all_signups
            if item["shift"]["date"] < today_str
            and item["status"] == STATUS_APPROVED
        ]

        # Ud af dem: kun dem hvor der IKKE er registreret timer endnu
        unlogged_signups = [
            item for item in past_approved
            if not item["work_hours"]
        ]

        # 🔥 NYT: tilføj co-workers til hver kommende vagt
        for item in upcoming_signups:
            shift_id = item["shift"]["id"]
            all_for_shift = database.get_signups_for_shift_with_hours(shift_id)

            # Vis kun andre, der er godkendt på vagten
            coworkers = [
                su for su in all_for_shift
                if su["status"] == STATUS_APPROVED
                and su["phone"] != phone_clean
            ]

            item["coworkers"] = coworkers

    return render_template(
        "mine_vagter.html",
        phone=phone,
        upcoming_signups=upcoming_signups,
        unlogged_signups=unlogged_signups,
        has_any_signups=has_any_signups,
    )

@app.route("/mine-vagter/historik")
@freelancer_required
def mine_vagter_historik():
    phone = session.get("freelancer_phone", "")
    if not phone:
        return redirect(url_for("freelancer_login"))

    all_signups = database.get_signups_by_phone(phone)

    # År dropdown: kun år der findes i data (fallback: i år)
    years = sorted({int(item["shift"]["date"][:4]) for item in all_signups if item.get("shift") and item["shift"].get("date")}) or [date.today().year]

    today = date.today()

    # Query params
    from_date_str = (request.args.get("from_date") or "").strip()
    to_date_str = (request.args.get("to_date") or "").strip()

    # Hurtigvalg (måned)
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month

    # Find earliest date i data (til hvis kun "til" er sat)
    earliest = None
    for item in all_signups:
        try:
            d = datetime.strptime(item["shift"]["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if earliest is None or d < earliest:
            earliest = d
    if earliest is None:
        earliest = today

    # Parse fra/til hvis udfyldt
    use_range = bool(from_date_str or to_date_str)
    from_date = None
    to_date = None
    period_label = None

    if use_range:
        if from_date_str:
            try:
                from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
            except Exception:
                from_date = None
        if to_date_str:
            try:
                to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
            except Exception:
                to_date = None

        # Defaults hvis kun én side er udfyldt
        if from_date is None:
            from_date = earliest
        if to_date is None:
            to_date = today

        # Clamp: vis aldrig fremtid
        if to_date > today:
            to_date = today

        # Swap hvis bruger vender dem om
        if from_date > to_date:
            from_date, to_date = to_date, from_date

        period_label = f"{from_date.strftime('%d-%m-%Y')} → {to_date.strftime('%d-%m-%Y')}"

    # Filtrér signups
    signups_in_period = []
    for item in all_signups:
        if item["status"] == STATUS_CANCELLED_BY_ADMIN:
            continue
        if item["status"] != STATUS_APPROVED:
            continue

        try:
            dt = datetime.strptime(item["shift"]["date"], "%Y-%m-%d").date()
        except Exception:
            continue

        # Vis aldrig fremtid (tidligst synlig på dagen)
        if dt > today:
            continue

        if use_range:
            if from_date <= dt <= to_date:
                signups_in_period.append(item)
        else:
            if dt.year == year and dt.month == month:
                signups_in_period.append(item)

    # Sortér (nyeste øverst)
    signups_in_period.sort(
        key=lambda it: it["shift"]["date"],
        reverse=True
    )

    # Beregn total baseret på admin-godkendt timetal hvis det findes
    def final_hours(item):
        if item.get("work_hours") is None:
            return 0.0
        if item.get("hours_approved_by_admin") and item.get("approved_work_hours") is not None:
            return float(item["approved_work_hours"])
        return float(item.get("work_hours") or 0.0)

    total_hours = sum(final_hours(item) for item in signups_in_period)

    return render_template(
        "mine_vagter_history.html",
        phone=phone,
        years=years,
        year=year,
        month=month,
        from_date=(from_date.isoformat() if use_range and from_date else ""),
        to_date=(to_date.isoformat() if use_range and to_date else ""),
        period_label=period_label,
        signups=signups_in_period,
        total_hours=total_hours,
    )


@app.post("/mine-vagter/timer/<int:signup_id>")
@freelancer_required
def freelancer_log_hours(signup_id):
    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)

    # Sikkerhed: sørg for at det er den rigtige freelancer
    session_phone = session.get("freelancer_phone")
    if not session_phone or signup["phone"] != session_phone:
        abort(403)

    work_start = request.form.get("work_start", "").strip()
    work_end = request.form.get("work_end", "").strip()

    if not work_start or not work_end:
        flash("Udfyld både start- og sluttid.")
        return redirect(url_for("mine_vagter", phone=session_phone))

    # Validér HH:MM og beregn timer
    try:
        start_dt = datetime.strptime(work_start, "%H:%M")
        end_dt = datetime.strptime(work_end, "%H:%M")
    except ValueError:
        flash("Tider skal være i format HH:MM.")
        return redirect(url_for("mine_vagter", phone=session_phone))

    delta = end_dt - start_dt
    if delta.total_seconds() < 0:
        # Hvis slut er "efter midnat" – antag næste dag
        delta += timedelta(days=1)

    hours = round(delta.total_seconds() / 3600.0, 2)

    database.set_signup_worked_hours(signup_id, work_start, work_end, hours)
    flash("Dine timer er gemt.")
    return redirect(url_for("mine_vagter", phone=session_phone))


@app.route("/anmod-fri/<int:signup_id>", methods=["POST"])
@freelancer_required
def anmod_fri(signup_id):
    signup = database.get_signup(signup_id)
    if signup is None:
        abort(404)

    phone = signup["phone"]

    if signup["status"] == STATUS_APPROVED:
        database.set_signup_status(signup_id, STATUS_RELEASE_REQUESTED)
        print("ANMODNING OM FRI:", signup_id)

    return redirect(url_for("mine_vagter", phone=phone))

@app.post("/annuller-tilmelding/<int:signup_id>")
@freelancer_required
def annuller_tilmelding(signup_id):
    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)

    # Sikkerhed: kun ejeren af tilmeldingen må annullere
    session_phone = session.get("freelancer_phone")
    if not session_phone or signup["phone"] != session_phone:
        abort(403)

    # Kun hvis den stadig afventer
    if signup["status"] != STATUS_REQUESTED:
        flash("Tilmeldingen kan ikke annulleres, fordi den allerede er behandlet.")
        return redirect(url_for("mine_vagter", phone=session_phone))

    database.delete_signup(signup_id)
    flash("Tilmeldingen er annulleret.")
    return redirect(url_for("mine_vagter", phone=session_phone))


@app.get("/api/signups-for-phone")
def api_signups_for_phone():
    """Brugt af forsiden til at markere vagter, man allerede er tilmeldt."""
    phone = request.args.get("phone", "").strip()
    if not phone:
        return jsonify({"signups": []})

    signups = database.get_signups_by_phone(phone)

    # Returnér også signup_id så vi kan fremelde direkte fra oversigten
    data = [
        {
            "shift_id": item["shift"]["id"],
            "signup_id": item["signup_id"],
            "status": item["status"],
        }
        for item in signups
        if item["status"] != STATUS_CANCELLED_BY_ADMIN
    ]
    return jsonify({"signups": data})




# ============================
# Admin login / logout
# ============================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None

    if request.method == "POST":
        password = request.form.get("password", "")

        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Forkert kodeord."

    return render_template("admin_login.html", error=error)



@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("landing"))

# ============================
# Admin dashboard + vagt-detaljer 
# ============================

@app.route("/admin")
@admin_required
def admin_dashboard():
    all_shifts = database.get_all_shifts_admin()
    active_shifts = [s for s in all_shifts if s["is_active"] == 1]
    archived_shifts = [s for s in all_shifts if s["is_active"] == 0]

    today = date.today()

    for s in active_shifts:
        needed = s.get("needed") or 0
        approved = s.get("approved") or 0
        row_class = ""

        # Prøv at parse datoen – hvis den fejler, lader vi bare rækken være uden farve
        try:
            shift_date = date.fromisoformat(s["date"])
            days_until = (shift_date - today).days
        except Exception:
            days_until = None

        # 1) Grøn: behov dækket
        if needed > 0 and approved >= needed:
            row_class = "shift-covered"

        # 2) Ikke dækket -> farve efter hvor tæt på vi er
        elif days_until is not None and days_until >= 0 and approved < needed:
            if days_until < 3:
                row_class = "shift-critical"      # rød
            elif days_until < 7:
                row_class = "shift-warning-7"     # orange
            elif days_until < 14:
                row_class = "shift-warning-14"    # gul
            else:
                row_class = ""  # mere end 14 dage væk: ingen farve

        s["row_class"] = row_class

    return render_template(
        "admin_dashboard.html",
        active_shifts=active_shifts,
        archived_shifts=archived_shifts,
    )

@app.get("/admin/actions")
@admin_required
def admin_actions():
    # Hent pending counts (samme kilde som din context_processor)
    pending = database.get_pending_admin_actions()

    # Hent shifts på samme måde som dashboard gør
    all_shifts = database.get_all_shifts_admin()
    active_shifts = [s for s in all_shifts if s.get("is_active") == 1]
    archived_shifts = [s for s in all_shifts if s.get("is_active") == 0]

    # Actionable = alt med pending > 0
    actionable = [s for s in (active_shifts + archived_shifts) if (s.get("pending") or 0) > 0]

    # Sortér: flest pending først, derefter dato/tid (fallback-safe)
    actionable.sort(
        key=lambda x: (
            x.get("pending", 0),
            x.get("date", ""),
            x.get("start_time", ""),
        ),
        reverse=True
    )

    return render_template(
        "admin_actions.html",
        actionable_shifts=actionable,
        pending_total=pending["pending_total"],
        pending_signups=pending["pending_signups"],
        pending_releases=pending["pending_releases"],
    )




@app.get("/admin/shifts/<int:shift_id>/edit")
@admin_required
def admin_edit_shift_form(shift_id):
    shift = database.get_shift(shift_id)
    if not shift:
        abort(404)

    # Tilføj felt med dansk dato-streng til brug i templaten
    shift["date_dk"] = format_danish_date(shift["date"])

    return render_template("admin_edit_shift.html", shift=shift)


@app.post("/admin/shifts/<int:shift_id>/edit")
@admin_required
def admin_edit_shift(shift_id):
    raw_date = request.form.get("date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    customer = request.form.get("customer", "").strip()
    event_type = request.form.get("event_type", "").strip()
    guest_count_raw = request.form.get("guest_count", "").strip()
    required_staff_raw = request.form.get("required_staff", "").strip()

    # ✅ NYT: admin note (vises til freelancere)
    admin_note = (request.form.get("admin_note") or "").strip() or None

    # Konverterer fx "11-12-2025" -> "2025-12-11"
    date_iso = parse_danish_date(raw_date)

    if not date_iso or not start_time or not location or not required_staff_raw:
        flash("Dato, starttid, sted og antal medarbejdere skal udfyldes.")
        return redirect(url_for("admin_edit_shift_form", shift_id=shift_id))

    try:
        required_staff = int(required_staff_raw)
    except ValueError:
        flash("Antal medarbejdere skal være et tal.")
        return redirect(url_for("admin_edit_shift_form", shift_id=shift_id))

    guest_count = None
    if guest_count_raw:
        try:
            guest_count = int(guest_count_raw)
        except ValueError:
            guest_count = None

    database.update_shift(
        shift_id,
        date_iso,
        start_time,
        location,
        description,
        required_staff,
        customer or None,
        event_type or None,
        guest_count,
        admin_note, 
    )

    flash("Vagten er opdateret.")
    return redirect(url_for("admin_shift_detail", shift_id=shift_id))

@app.route("/admin/shift/<int:shift_id>/note", methods=["POST"])
@admin_required
def admin_set_shift_note(shift_id: int):
    note = request.form.get("admin_note", "").strip()
    database.set_shift_admin_note(shift_id, note if note else None)
    return redirect(url_for("admin_overview") + f"#shift-{shift_id}")

@app.route("/admin/shift/<int:shift_id>", methods=["GET"])
@admin_required
def admin_shift_detail(shift_id):
    shift = database.get_shift(shift_id)
    if shift is None:
        abort(404)

    # Tilføj dansk dato til brug i templaten
    shift["date_dk"] = format_danish_date(shift["date"])

    signups = database.get_signups_for_shift(shift_id)
    persons = database.get_all_persons()  # til dropdown

    return render_template(
        "admin_shift.html",
        shift=shift,
        signups=signups,
        persons=persons,
    )


@app.route("/admin/overblik")
@admin_required
def admin_overview():
    all_shifts = database.get_all_shifts_admin()
    today_str = date.today().isoformat()

    upcoming_shifts = [
        s for s in all_shifts
        if s.get("is_active") == 1 and s.get("date") and s["date"] >= today_str
    ]

    overview = []
    for shift in upcoming_shifts:
        signups = database.get_signups_for_shift(shift["id"])

        approved_signups = [s for s in signups if s["status"] == STATUS_APPROVED]
        requested_signups = [s for s in signups if s["status"] == STATUS_REQUESTED]
        release_requested_signups = [s for s in signups if s["status"] == STATUS_RELEASE_REQUESTED]

        overview.append({
            "shift": shift,
            "signups": signups,  # NYT: alle tilmeldinger
            "approved_signups": approved_signups,  # beholdes for bagudkompabilitet
            "counts": {
                "total": len(signups),
                "approved": len(approved_signups),
                "requested": len(requested_signups),
                "release_requested": len(release_requested_signups),
            }
        })

    # Sortér efter dato/tid så den ikke virker random
    overview.sort(key=lambda x: (x["shift"].get("date", ""), x["shift"].get("time", "")))

    return render_template("admin_overview.html", overview=overview)

@app.route("/admin/timer", methods=["GET"])
@admin_required
def admin_timer():
    now = datetime.now()

    # ---- params ----
    try:
        year = int(request.args.get("year", now.year))
    except ValueError:
        year = now.year

    try:
        month = int(request.args.get("month", now.month))
    except ValueError:
        month = now.month

    show_paid = request.args.get("show_paid") == "1"

    # dropdown years
    years = list(range(now.year - 2, now.year + 3))

    # ---- hent rækker (din funktion) ----
    rows = database.get_hours_for_month(
        year=year,
        month=month,
        include_paid=show_paid,
        include_missing=True,  # behold hvis du vil se "timer mangler" rækker
    )

    # ---- group + summer ----
    people_map = {}
    grand_total = 0.0

    for r in rows:
        name = (r.get("person_name") or "Ukendt").strip()
        phone = (r.get("phone") or "").strip()
        key = f"{name}::{phone}"

        if key not in people_map:
            people_map[key] = {
                "name": name,
                "phone": phone,
                "rows": [],
                "total_hours": 0.0,
            }

        approved_flag = bool(r.get("hours_approved_by_admin"))
        work_hours = r.get("work_hours", None)
        approved_work_hours = r.get("approved_work_hours", None)

        final_hours = approved_work_hours if approved_flag else work_hours
        add = float(final_hours) if final_hours is not None else 0.0

        people_map[key]["rows"].append(r)
        people_map[key]["total_hours"] += add
        grand_total += add

    people = sorted(people_map.values(), key=lambda p: (p["name"].lower(), p["phone"]))

    return render_template(
        "admin_timer.html",
        people=people,
        years=years,
        year=year,
        month=month,
        show_paid=show_paid,
        grand_total=grand_total,
    )

@app.get("/admin/historik")
@admin_required
def admin_history():
    """
    Viser alle historiske arrangementer (is_active = -1),
    grupperet efter år og måned, med deltagere og registrerede timer.
    """
    historic_shifts = database.get_historic_shifts()

    # Gruppér efter (år, måned)
    groups = {}
    for s in historic_shifts:
        date_str = s["date"] or ""
        try:
            year = int(date_str[:4])
            month = int(date_str[5:7])
        except Exception:
            year, month = 0, 0

        key = (year, month)
        if key not in groups:
            groups[key] = {
                "year": year,
                "month": month,
                "entries": [],  # liste af {shift, signups, total_hours}
            }

        signups = database.get_signups_for_shift_with_hours(s["id"])
        total_hours = sum((su["work_hours"] or 0) for su in signups)

        groups[key]["entries"].append(
            {
                "shift": s,
                "signups": signups,
                "total_hours": total_hours,
            }
        )

    # Sorter måneder nyeste først
    months = sorted(
        groups.values(),
        key=lambda g: (g["year"], g["month"]),
        reverse=True,
    )

    # Indenfor hver måned: sorter vagter efter dato/tid (nyest øverst)
    for g in months:
        g["entries"].sort(
            key=lambda e: (e["shift"]["date"], e["shift"]["time"]),
            reverse=True,
        )

    return render_template("admin_history.html", months=months)

@app.post("/admin/historik/revive/<int:shift_id>")
@admin_required
def admin_revive_shift(shift_id: int):
    """Flyt et arrangement fra historik (-1) tilbage til arkiv (0)."""
    database.revive_historic_shift(shift_id)
    flash("Arrangement genåbnet (flyttet til arkiverede).")
    return redirect(url_for("admin_history"))


@app.post("/admin/historik/delete/<int:shift_id>")
@admin_required
def admin_delete_shift(shift_id: int):
    """Slet et arrangement permanent (inkl. alle tilmeldinger)."""
    database.delete_shift_permanently(shift_id)
    flash("Arrangement slettet permanent.")
    return redirect(url_for("admin_history"))


@app.post("/admin/timer/mark-paid/<int:signup_id>")
@admin_required
def admin_timer_mark_paid(signup_id):
    # Skal vi sætte eller rydde "afregnet"?
    paid_flag = request.form.get("paid", "1") == "1"

    # Bruges til at hoppe tilbage til samme måned/visning
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)
    show_paid = request.form.get("show_paid", "0")

    # 🔐 KRITISK CHECK: timer skal være godkendt før afregning
    signup = database.get_signup_by_id(signup_id)

    if not signup:
        flash("Kunne ikke finde tilmeldingen.")
        return redirect(url_for("admin_timer", year=year, month=month, show_paid=show_paid))

    if paid_flag and not signup.get("hours_approved_by_admin"):
        flash("Timer skal godkendes før afregning.")
        return redirect(url_for("admin_timer", year=year, month=month, show_paid=show_paid))

    # OK → udfør afregning / fortryd
    database.set_signup_payroll_status(signup_id, paid_flag)

    flash(
        "Timer markeret som afregnet."
        if paid_flag
        else "Afregning for denne vagt er nulstillet."
    )

    return redirect(url_for("admin_timer", year=year, month=month, show_paid=show_paid))





@app.post("/admin/timer/approve/<int:signup_id>")
@admin_required
def admin_timer_approve(signup_id: int):
    approved = request.form.get("approved_work_hours")

    try:
        approved = float(approved)
        if approved < 0 or approved > 24:
            raise ValueError()
    except Exception:
        flash("Ugyldigt antal timer.")
        return redirect(request.referrer or url_for("admin_timer"))

    database.approve_work_hours(signup_id, approved)
    flash("Timer godkendt.")
    return redirect(request.referrer or url_for("admin_timer"))



# ============================
# ADMIN ACTIONS (tilmeldinger)
# ============================

@app.post("/admin/signups/<int:signup_id>/approve")
@admin_required
def admin_approve_signup(signup_id):
    """Godkend en tilmelding (REQUESTED -> APPROVED), men aldrig over kapacitet."""
    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)

    # Find vagt og tjek hvor mange der allerede er godkendt
    shift = database.get_shift(signup["shift_id"])
    if not shift:
        abort(404)

    approved = shift["approved"]      # allerede godkendte
    needed = shift["needed"]          # hvor mange der er brug for

    if approved >= needed:
        # Vagt er allerede fuld – vi ændrer ingenting, giver bare besked
        flash("Vagten er allerede fyldt. Du kan ikke godkende flere på den.")
        return redirect(url_for("admin_shift_detail", shift_id=signup["shift_id"]))

    # Der er stadig plads – godkend tilmeldingen
    database.set_signup_status(signup_id, STATUS_APPROVED)
    flash("Tilmelding godkendt.")

    return redirect(url_for("admin_shift_detail", shift_id=signup["shift_id"]))

@app.post("/admin/shift/<int:shift_id>/add-signup")
@admin_required
def admin_add_signup(shift_id):
    """Tilføj en eksisterende person til en vagt som tilmelding (REQUESTED)."""
    person_id_raw = request.form.get("person_id", "").strip()
    if not person_id_raw:
        flash("Vælg en person for at tilføje til vagten.")
        return redirect(url_for("admin_shift_detail", shift_id=shift_id))

    try:
        person_id = int(person_id_raw)
    except ValueError:
        flash("Ugyldigt valg af person.")
        return redirect(url_for("admin_shift_detail", shift_id=shift_id))

    person = database.get_person(person_id)
    if not person:
        flash("Personen findes ikke længere.")
        return redirect(url_for("admin_shift_detail", shift_id=shift_id))

    # Opret tilmelding – create_signup bruger selv get_or_create_person,
    # men vi sender name + phone for at ramme den rigtige.
    signup_id = database.create_signup(
        shift_id=shift_id,
        name=person["name"],
        phone=person["phone"],
        initial_status=STATUS_REQUESTED,
        available_from=None,
    )

    if signup_id is None:
        flash("Personen er allerede tilmeldt denne vagt.")
    else:
        flash(f"{person['name']} er nu tilmeldt vagten (afventer godkendelse).")

    return redirect(url_for("admin_shift_detail", shift_id=shift_id))


@app.post("/admin/shifts/new")
@admin_required
def admin_create_shift():
    raw_date = request.form.get("date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    customer = request.form.get("customer", "").strip()
    event_type = request.form.get("event_type", "").strip()
    guest_count_raw = request.form.get("guest_count", "").strip()
    required_staff_raw = request.form.get("required_staff", "").strip()

    # ✅ NYT: admin note (vises til freelancere)
    admin_note = (request.form.get("admin_note") or "").strip() or None

    # Konverter dato til ISO
    date_iso = parse_danish_date(raw_date)

    if not date_iso or not start_time or not location or not required_staff_raw:
        flash("Dato, starttid, sted og antal medarbejdere skal udfyldes.")
        return redirect(url_for("admin_dashboard"))

    try:
        required_staff = int(required_staff_raw)
    except ValueError:
        flash("Antal medarbejdere skal være et tal.")
        return redirect(url_for("admin_dashboard"))

    guest_count = None
    if guest_count_raw:
        try:
            guest_count = int(guest_count_raw)
        except ValueError:
            guest_count = None  # bare dropper det, hvis det er noget skørt

    # Forudsætter at database.create_shift er udvidet til også at tage de nye felter
    database.create_shift(
        date_iso,
        start_time,
        location,
        description,
        required_staff,
        customer or None,
        event_type or None,
        guest_count,
        admin_note,
    )

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/signups/<int:signup_id>/reject")
@admin_required
def admin_reject_signup(signup_id):
    """Afvis/fjern en tilmelding helt – så personen kan melde sig til igen senere."""
    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)

    # Slet tilmeldingen helt
    database.delete_signup(signup_id)

    return redirect(url_for("admin_shift_detail", shift_id=signup["shift_id"]))


@app.post("/admin/signups/<int:signup_id>/release-approve")
@admin_required
def admin_release_approve(signup_id):
    """
    Godkend afbud: personen fjernes helt fra vagten.
    Efterfølgende kan de melde sig til igen, hvis der stadig er brug for folk.
    """
    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)

    # Slet tilmeldingen helt
    database.delete_signup(signup_id)

    return redirect(url_for("admin_shift_detail", shift_id=signup["shift_id"]))



@app.post("/admin/signups/<int:signup_id>/release-deny")
@admin_required
def admin_release_deny(signup_id):
    """
    Afvis afbud (RELEASE_REQUESTED -> APPROVED).
    Personen forbliver på vagten.
    """
    database.set_signup_status(signup_id, STATUS_APPROVED)
    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)
    return redirect(url_for("admin_shift_detail", shift_id=signup["shift_id"]))

@app.post("/admin/shifts/<int:shift_id>/set-active")
@admin_required
def admin_set_shift_active(shift_id):
    # is_active kan være "1" (aktiv), "0" (arkiv) eller "-1" (historik/sink)
    state_raw = request.form.get("is_active", "1").strip()

    if state_raw not in {"1", "0", "-1"}:
        state_raw = "1"  # defensiv default

    state = int(state_raw)
    database.set_shift_state(shift_id, state)

    return redirect(url_for("admin_dashboard"))



@app.post("/admin/shifts/sink-archived")
@admin_required
def admin_sink_all_archived():
    database.sink_all_archived_shifts()
    flash("Alle arkiverede arrangementer er flyttet til historikken.")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/extra/approve/<int:extra_id>")
@admin_required
def admin_extra_approve(extra_id: int):
    approved = request.form.get("approved_work_hours")

    try:
        approved = float(approved)
        if approved < 0 or approved > 24:
            raise ValueError()
    except Exception:
        flash("Ugyldigt antal timer.")
        return redirect(request.referrer or url_for("admin_timer"))

    database.approve_extra_work_hours(extra_id, approved)
    flash("Ekstratimer godkendt.")
    return redirect(request.referrer or url_for("admin_timer"))


@app.post("/admin/extra/reject/<int:extra_id>")
@admin_required
def admin_extra_reject(extra_id: int):
    database.reject_extra_shift(extra_id)
    flash("Ekstravagt afvist.")
    return redirect(request.referrer or url_for("admin_timer"))


@app.post("/admin/extra/mark-paid/<int:extra_id>")
@admin_required
def admin_extra_mark_paid(extra_id: int):
    paid_flag = request.form.get("paid", "1") == "1"

    extra = database.get_extra_shift_by_id(extra_id)
    if not extra:
        flash("Kunne ikke finde ekstravagten.")
        return redirect(request.referrer or url_for("admin_timer"))

    # KRITISK: skal være godkendt først
    if not extra.get("hours_approved_by_admin"):
        flash("Godkend timer før afregning.")
        return redirect(request.referrer or url_for("admin_timer"))

    database.mark_extra_paid(extra_id, paid_flag)
    flash("Ekstratimer markeret afregnet." if paid_flag else "Ekstratimer markeret ikke-afregnet.")
    return redirect(request.referrer or url_for("admin_timer"))



@app.post("/admin/signups/<int:signup_id>/meet-time")
@admin_required
def admin_set_meet_time(signup_id):
    """
    Sæt / opdater mødetid for en tilmelding.
    Tomt felt = nulstil mødetid.
    """
    meet_time = request.form.get("meet_time", "").strip()
    if not meet_time:
        meet_time = None

    database.set_signup_meet_time(signup_id, meet_time)

    signup = database.get_signup(signup_id)
    if not signup:
        abort(404)
    return redirect(url_for("admin_shift_detail", shift_id=signup["shift_id"]))


if __name__ == "__main__":
    app.run(debug=True)



import os
import secrets
from datetime import datetime, timedelta
from flask import (Flask, render_template, redirect, url_for, request,
                   session, jsonify, flash)
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from db import DB, CATS, MEMBER_COLORS

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-xyz987")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Connecte-toi pour accéder à l'application."

db = DB()

MOIS_FR = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
           "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]

CURRENCIES = [
    {"symbol": "€",   "label": "🇫🇷 Euro — €"},
    {"symbol": "MAD", "label": "🇲🇦 Dirham marocain — MAD"},
    {"symbol": "DZD", "label": "🇩🇿 Dinar algérien — DZD"},
    {"symbol": "TND", "label": "🇹🇳 Dinar tunisien — TND"},
    {"symbol": "XOF", "label": "🇸🇳 Franc CFA — XOF"},
    {"symbol": "£",   "label": "🇬🇧 Livre sterling — £"},
    {"symbol": "CHF", "label": "🇨🇭 Franc suisse — CHF"},
    {"symbol": "$",   "label": "🇺🇸 Dollar américain — $"},
    {"symbol": "CAD", "label": "🇨🇦 Dollar canadien — CAD"},
    {"symbol": "AED", "label": "🇦🇪 Dirham émirati — AED"},
    {"symbol": "SAR", "label": "🇸🇦 Riyal saoudien — SAR"},
    {"symbol": "TRY", "label": "🇹🇷 Livre turque — TRY"},
]

_VALID_CURRENCIES = {c["symbol"] for c in CURRENCIES}


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.email = row["email"]
        self.household_name = row["household_name"]
        self.is_admin = bool(row["is_admin"]) if "is_admin" in row.keys() else False
        self.currency = row["currency"] if "currency" in row.keys() and row["currency"] else "€"


@login_manager.user_loader
def load_user(uid):
    row = db.get_user_by_id(int(uid))
    return User(row) if row else None


def get_period():
    now = datetime.now()
    y = request.args.get("y", session.get("period_year", now.year), type=int)
    m = request.args.get("m", session.get("period_month", now.month), type=int)
    if not (1 <= m <= 12):
        m = now.month
    session["period_year"] = y
    session["period_month"] = m
    return y, m


def prev_period(y, m):
    if m == 1:
        return y - 1, 12
    return y, m - 1


def next_period(y, m):
    if m == 12:
        return y + 1, 1
    return y, m + 1


def fmt_money(val):
    """Format number as French-style: 1 234,56 <devise>"""
    try:
        val = float(val)
    except (TypeError, ValueError):
        val = 0.0
    parts = f"{val:.2f}".split(".")
    integer = parts[0]
    decimals = parts[1]
    if len(integer) > 3:
        groups = []
        while integer:
            groups.append(integer[-3:])
            integer = integer[:-3]
        integer = " ".join(reversed(groups))
    try:
        symbol = current_user.currency if current_user.is_authenticated else "€"
    except Exception:
        symbol = "€"
    return f"{integer},{decimals} {symbol}"


app.jinja_env.filters["money"] = fmt_money


# ── Auth ───────────────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd = request.form.get("password", "")
        pwd2 = request.form.get("password2", "")
        household = request.form.get("household_name", "").strip()
        if not email or not pwd:
            flash("Email et mot de passe requis.", "error")
            return render_template("register.html")
        if pwd != pwd2:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template("register.html")
        if len(pwd) < 6:
            flash("Mot de passe trop court (6 caractères min).", "error")
            return render_template("register.html")
        if not household:
            flash("Donne un nom au foyer.", "error")
            return render_template("register.html")
        uid = db.create_user(email, generate_password_hash(pwd), household)
        if uid is None:
            flash("Cet email est déjà utilisé.", "error")
            return render_template("register.html")
        session["pending_uid"] = uid
        try:
            _send_welcome_email(email, household)
        except Exception as e:
            app.logger.error("Brevo welcome email error: %s", e)
        return redirect(url_for("setup"))
    return render_template("register.html")


@app.route("/setup", methods=["GET", "POST"])
def setup():
    uid = session.get("pending_uid")
    if not uid and not current_user.is_authenticated:
        return redirect(url_for("register"))
    if current_user.is_authenticated:
        uid = current_user.id

    if request.method == "POST":
        names = request.form.getlist("member_name[]")
        roles = request.form.getlist("member_role[]")

        names = [n.strip() for n in names if n.strip()]
        if not names:
            flash("Ajoute au moins un membre.", "error")
            return render_template("setup.html")

        db.delete_all_members(uid)
        for i, name in enumerate(names):
            role = roles[i] if i < len(roles) else "Parent"
            is_payer = (role in ("Payeur", "Parent"))
            color = MEMBER_COLORS[i % len(MEMBER_COLORS)]
            db.add_member(uid, name, role, is_payer, color)

        if "pending_uid" in session:
            session.pop("pending_uid")
            row = db.get_user_by_id(uid)
            login_user(User(row))
        flash("Foyer configuré !", "success")
        return redirect(url_for("dashboard"))

    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd = request.form.get("password", "")
        row = db.get_user_by_email(email)
        if row and check_password_hash(row["password_hash"], pwd):
            if row["blocked"]:
                flash("Ton compte a été suspendu. Contacte l'administrateur.", "error")
                return render_template("login.html")
            login_user(User(row), remember=request.form.get("remember") == "on")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Email ou mot de passe incorrect.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Period API ─────────────────────────────────────────────────────────────

@app.route("/api/period")
@login_required
def api_period():
    y = request.args.get("y", type=int)
    m = request.args.get("m", type=int)
    if y and m and 1 <= m <= 12:
        session["period_year"] = y
        session["period_month"] = m
    return jsonify(ok=True)


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    uid = current_user.id
    y, m = get_period()
    members = db.get_members(uid)
    payers = [mb for mb in members if mb["is_payer"]]
    beneficiaires = [mb for mb in members if not mb["is_payer"]]

    totaux_payeur = db.get_totaux_payeur(uid, y, m)
    totaux_pour = db.get_totaux_pour(uid, y, m)
    totaux_cat = db.get_totaux_cat(uid, y, m)
    revenus = db.get_total_revenus(uid, y, m)
    total_dep = sum(totaux_payeur.values())
    epargne = revenus - total_dep
    budgets = db.get_budgets(uid)
    last_dep = db.get_last_depenses(uid, y, m, 10)

    budget_bars = []
    for cat in CATS:
        spent = totaux_cat.get(cat, 0)
        plafond = budgets.get(cat, 0)
        pct = (spent / plafond * 100) if plafond > 0 else 0
        color = "ok" if pct < 75 else ("warn" if pct < 100 else "danger")
        budget_bars.append({
            "cat": cat, "spent": spent, "plafond": plafond,
            "pct": min(pct, 100), "color": color, "over": pct >= 100
        })

    color_map = {mb["name"]: mb["color"] for mb in members}
    color_map["Commun"] = "#8a8d99"
    pie_data = {
        "labels": list(totaux_payeur.keys()),
        "data": list(totaux_payeur.values()),
        "colors": [color_map.get(k, "#8a8d99") for k in totaux_payeur.keys()]
    }

    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)

    return render_template("dashboard.html",
        y=y, m=m, mois_fr=MOIS_FR[m],
        py=py, pm=pm, ny=ny, nm=nm,
        members=members, payers=payers, beneficiaires=beneficiaires,
        totaux_payeur=totaux_payeur, totaux_pour=totaux_pour,
        revenus=revenus, total_dep=total_dep, epargne=epargne,
        budget_bars=budget_bars, last_dep=last_dep,
        pie_data=pie_data, color_map=color_map,
        household=current_user.household_name
    )


# ── Transactions ───────────────────────────────────────────────────────────

@app.route("/transactions")
@login_required
def transactions():
    uid = current_user.id
    y, m = get_period()
    members = db.get_members(uid)
    payers = [mb for mb in members if mb["is_payer"]]
    depenses = db.get_depenses(uid, y, m)
    totaux_payeur = db.get_totaux_payeur(uid, y, m)
    total_dep = sum(totaux_payeur.values())
    color_map = {mb["name"]: mb["color"] for mb in members}
    color_map["Commun"] = "#8a8d99"

    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)

    return render_template("transactions.html",
        y=y, m=m, mois_fr=MOIS_FR[m],
        py=py, pm=pm, ny=ny, nm=nm,
        members=members, payers=payers,
        depenses=depenses, CATS=CATS,
        totaux_payeur=totaux_payeur, total_dep=total_dep,
        color_map=color_map,
        now_day=datetime.now().day
    )


# ── Stats ──────────────────────────────────────────────────────────────────

@app.route("/stats")
@login_required
def stats():
    uid = current_user.id
    y, m = get_period()
    members = db.get_members(uid)
    payers = [mb for mb in members if mb["is_payer"]]
    beneficiaires = [mb for mb in members if not mb["is_payer"]]
    color_map = {mb["name"]: mb["color"] for mb in members}
    color_map["Commun"] = "#8a8d99"

    totaux_payeur = db.get_totaux_payeur(uid, y, m)
    totaux_pour = db.get_totaux_pour(uid, y, m)
    totaux_cat = db.get_totaux_cat(uid, y, m)
    totaux_cat_par_payeur = db.get_totaux_cat_par_payeur(uid, y, m)
    budgets = db.get_budgets(uid)
    revenus = db.get_total_revenus(uid, y, m)
    total_dep = sum(totaux_payeur.values())
    epargne = revenus - total_dep

    # Fixes vs variables
    total_fixes = db.get_total_by_type(uid, y, m, "Fixe")
    total_variables = db.get_total_by_type(uid, y, m, "Variable")

    # Pour les enfants/bénéficiaires
    total_enfants = sum(totaux_pour.get(mb["name"], 0) for mb in beneficiaires)

    pie_payeur = {
        "labels": list(totaux_payeur.keys()),
        "data": list(totaux_payeur.values()),
        "colors": [color_map.get(k, "#8a8d99") for k in totaux_payeur]
    }
    pie_pour = {
        "labels": list(totaux_pour.keys()),
        "data": list(totaux_pour.values()),
        "colors": [color_map.get(k, "#8a8d99") for k in totaux_pour]
    }

    cat_bar = []
    for cat in CATS:
        entry = {"cat": cat, "total": totaux_cat.get(cat, 0), "payeurs": []}
        for p in payers:
            entry["payeurs"].append({
                "name": p["name"],
                "color": p["color"],
                "val": totaux_cat_par_payeur.get(cat, {}).get(p["name"], 0)
            })
        cat_bar.append(entry)

    budget_bars = []
    for cat in CATS:
        spent = totaux_cat.get(cat, 0)
        plafond = budgets.get(cat, 0)
        pct = (spent / plafond * 100) if plafond > 0 else 0
        color = "ok" if pct < 75 else ("warn" if pct < 100 else "danger")
        budget_bars.append({
            "cat": cat, "spent": spent, "plafond": plafond,
            "pct": min(pct, 100), "color": color, "over": pct >= 100
        })

    # Evolution last 6 months
    evolution = []
    cy, cm = y, m
    for _ in range(6):
        dep_m = db.get_totaux_payeur(uid, cy, cm)
        rev_m = db.get_total_revenus(uid, cy, cm)
        total_m = sum(dep_m.values())
        evolution.insert(0, {
            "label": f"{MOIS_FR[cm][:3]} {cy}",
            "dep": round(total_m, 2),
            "rev": round(rev_m, 2),
            "epargne": round(rev_m - total_m, 2)
        })
        cy, cm = prev_period(cy, cm)

    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)

    return render_template("stats.html",
        y=y, m=m, mois_fr=MOIS_FR[m],
        py=py, pm=pm, ny=ny, nm=nm,
        members=members, payers=payers, beneficiaires=beneficiaires,
        color_map=color_map,
        pie_payeur=pie_payeur, pie_pour=pie_pour,
        cat_bar=cat_bar, budget_bars=budget_bars,
        revenus=revenus, total_dep=total_dep, epargne=epargne,
        total_fixes=total_fixes, total_variables=total_variables,
        total_enfants=total_enfants,
        evolution=evolution
    )


# ── Settings ───────────────────────────────────────────────────────────────

@app.route("/settings")
@login_required
def settings():
    uid = current_user.id
    y, m = get_period()
    members = db.get_members(uid)
    payers = [mb for mb in members if mb["is_payer"]]
    salaires = db.get_salaires(uid, y, m)
    budgets = db.get_budgets(uid)
    color_map = {mb["name"]: mb["color"] for mb in members}

    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)

    return render_template("settings.html",
        y=y, m=m, mois_fr=MOIS_FR[m],
        py=py, pm=pm, ny=ny, nm=nm,
        members=members, payers=payers,
        salaires=salaires, budgets=budgets, CATS=CATS,
        color_map=color_map,
        household=current_user.household_name,
        currency=current_user.currency,
        CURRENCIES=CURRENCIES,
    )


# ── API Dépenses ───────────────────────────────────────────────────────────

@app.route("/api/depense/add", methods=["POST"])
@login_required
def api_depense_add():
    uid = current_user.id
    try:
        data = request.get_json() or request.form
        y, m = get_period()
        dep_id = db.add_depense(
            uid,
            int(data.get("annee", y)),
            int(data.get("mois", m)),
            int(data.get("jour", 1)),
            float(data.get("montant", 0)),
            data.get("categorie", "Divers"),
            data.get("description", ""),
            data.get("personne", ""),
            data.get("type_dep", "Variable"),
            data.get("pour_qui", "Commun")
        )
        return jsonify(ok=True, id=dep_id)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.route("/api/depense/<int:dep_id>/edit", methods=["POST"])
@login_required
def api_depense_edit(dep_id):
    uid = current_user.id
    try:
        data = request.get_json() or request.form
        db.update_depense(
            uid, dep_id,
            int(data.get("jour", 1)),
            float(data.get("montant", 0)),
            data.get("categorie", "Divers"),
            data.get("description", ""),
            data.get("personne", ""),
            data.get("type_dep", "Variable"),
            data.get("pour_qui", "Commun")
        )
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@app.route("/api/depense/<int:dep_id>/delete", methods=["POST"])
@login_required
def api_depense_delete(dep_id):
    uid = current_user.id
    try:
        db.delete_depense(uid, dep_id)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── API Salaires ───────────────────────────────────────────────────────────

@app.route("/api/salaires/save", methods=["POST"])
@login_required
def api_salaires_save():
    uid = current_user.id
    y, m = get_period()
    try:
        data = request.get_json() or {}
        payers = db.get_payers(uid)
        for p in payers:
            key = f"sal_{p['id']}"
            if key in data:
                db.save_salaire(uid, y, m, p["id"], float(data[key] or 0))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── API Budgets ────────────────────────────────────────────────────────────

@app.route("/api/budgets/save", methods=["POST"])
@login_required
def api_budgets_save():
    uid = current_user.id
    try:
        data = request.get_json() or {}
        for cat in CATS:
            key = f"budget_{cat}"
            if key in data:
                db.set_budget(uid, cat, float(data[key] or 0))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── API Currency ──────────────────────────────────────────────────────────

@app.route("/api/currency/save", methods=["POST"])
@login_required
def api_currency_save():
    uid = current_user.id
    try:
        data = request.get_json() or {}
        symbol = data.get("currency", "€").strip()
        if symbol not in _VALID_CURRENCIES:
            return jsonify(ok=False, error="Devise invalide"), 400
        db.set_currency(uid, symbol)
        current_user.currency = symbol
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── API Household ──────────────────────────────────────────────────────────

@app.route("/api/household/save", methods=["POST"])
@login_required
def api_household_save():
    uid = current_user.id
    try:
        data = request.get_json() or {}
        household = data.get("household_name", "").strip()
        if household:
            db.update_household_name(uid, household)
            current_user.household_name = household

        members_data = data.get("members", [])
        if members_data:
            db.delete_all_members(uid)
            for i, mb in enumerate(members_data):
                name = mb.get("name", "").strip()
                if not name:
                    continue
                role = mb.get("role", "Parent")
                is_payer = (role in ("Payeur", "Parent"))
                color = MEMBER_COLORS[i % len(MEMBER_COLORS)]
                db.add_member(uid, name, role, is_payer, color)

        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── API Salaires reset ─────────────────────────────────────────────────────

@app.route("/api/salaires/reset", methods=["POST"])
@login_required
def api_salaires_reset():
    uid = current_user.id
    y, m = get_period()
    try:
        data = request.get_json() or {}
        member_id = int(data.get("member_id", 0))
        db.reset_salaire(uid, y, m, member_id)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── Reconduire fixes ───────────────────────────────────────────────────────

@app.route("/settings/reconduire_fixes", methods=["POST"])
@login_required
def reconduire_fixes():
    uid = current_user.id
    y, m = get_period()
    py, pm = prev_period(y, m)
    try:
        count = db.reconduire_fixes(uid, py, pm, y, m)
        return jsonify(ok=True, count=count)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


# ── Contact ────────────────────────────────────────────────────────────────

@app.route("/contact", methods=["GET", "POST"])
def contact():
    now = datetime.now()
    y, m = now.year, now.month
    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip().lower()
        telephone = request.form.get("telephone", "").strip()
        message = request.form.get("message", "").strip()
        if not nom or not email or not message:
            flash("Nom, email et message sont requis.", "error")
            return render_template("contact.html",
                y=y, m=m, mois_fr=MOIS_FR[m], py=py, pm=pm, ny=ny, nm=nm)
        db.add_contact_message(nom, email, telephone, message)
        try:
            _send_contact_notification(nom, email, telephone, message)
        except Exception as e:
            app.logger.error("Brevo contact notification error: %s", e)
        flash("Message envoyé ! Nous te répondrons dès que possible.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html",
        y=y, m=m, mois_fr=MOIS_FR[m], py=py, pm=pm, ny=ny, nm=nm)


# ── Admin ───────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
def admin():
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "error")
        return redirect(url_for("dashboard"))
    now = datetime.now()
    y, m = now.year, now.month
    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)
    stats = db.get_admin_stats()
    users = db.get_all_users()
    messages = db.get_contact_messages()
    return render_template("admin.html",
        stats=stats, users=users, messages=messages,
        y=y, m=m, mois_fr=MOIS_FR[m],
        py=py, pm=pm, ny=ny, nm=nm
    )


@app.route("/admin/users/<int:uid>/block", methods=["POST"])
@login_required
def admin_block_user(uid):
    if not current_user.is_admin:
        return jsonify(ok=False), 403
    db.block_user(uid)
    return jsonify(ok=True)


@app.route("/admin/users/<int:uid>/unblock", methods=["POST"])
@login_required
def admin_unblock_user(uid):
    if not current_user.is_admin:
        return jsonify(ok=False), 403
    db.unblock_user(uid)
    return jsonify(ok=True)


@app.route("/admin/messages")
@login_required
def admin_messages():
    if not current_user.is_admin:
        flash("Accès réservé à l'administrateur.", "error")
        return redirect(url_for("dashboard"))
    messages = db.get_contact_messages()
    return render_template("admin_messages.html", messages=messages)


@app.route("/admin/messages/<int:msg_id>/lu", methods=["POST"])
@login_required
def admin_mark_lu(msg_id):
    if not current_user.is_admin:
        return jsonify(ok=False), 403
    db.mark_message_lu(msg_id)
    return jsonify(ok=True)


@app.route("/admin/send_email", methods=["POST"])
@login_required
def admin_send_email():
    if not current_user.is_admin:
        return jsonify(ok=False), 403
    import requests as _req

    data = request.get_json() or {}
    subject = (data.get("subject") or "").strip()
    html_content = (data.get("html_content") or "").strip()
    target = data.get("target", "all")
    specific_email = (data.get("specific_email") or "").strip()

    if not subject or not html_content:
        return jsonify(ok=False, error="Objet et corps de l'email sont requis."), 400

    api_key = os.environ.get("BREVO_API_KEY", "")
    from_email = os.environ.get("MAIL_FROM", "noreply@budget-familial.app")

    if target == "specific":
        if not specific_email:
            return jsonify(ok=False, error="Adresse email requise."), 400
        recipients = [specific_email]
    else:
        all_users = db.get_all_users()
        recipients = [u["email"] for u in all_users if u["email"]]

    sent = 0
    failed = 0
    errors = []

    for email_addr in recipients:
        payload = {
            "sender": {"email": from_email, "name": "Budget Familial"},
            "to": [{"email": email_addr}],
            "replyTo": {"email": "contact.budgetfamilial@gmail.com"},
            "subject": subject,
            "htmlContent": html_content,
        }
        try:
            resp = _req.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            sent += 1
        except Exception as e:
            failed += 1
            errors.append(f"{email_addr}: {str(e)[:100]}")

    return jsonify(ok=True, sent=sent, failed=failed, errors=errors)


# ── Guide ──────────────────────────────────────────────────────────────────

@app.route("/guide")
@login_required
def guide():
    now = datetime.now()
    y, m = now.year, now.month
    py, pm = prev_period(y, m)
    ny, nm = next_period(y, m)
    return render_template("guide.html",
        y=y, m=m, mois_fr=MOIS_FR[m],
        py=py, pm=pm, ny=ny, nm=nm
    )


# ── Emails transactionnels ─────────────────────────────────────────────────

def _send_welcome_email(to_email, household_name):
    import requests as _req
    api_key = os.environ.get("BREVO_API_KEY", "")
    from_email = os.environ.get("MAIL_FROM", "noreply@budget-familial.app")
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 16px">
  <tr><td align="center">
    <table width="100%" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)">

      <!-- Header -->
      <tr>
        <td style="background:linear-gradient(135deg,#1e3a5f 0%,#2563a8 100%);padding:36px 40px;text-align:center">
          <div style="font-size:28px;font-weight:700;color:#ffffff;letter-spacing:-.5px">Budget Familial</div>
          <div style="font-size:13px;color:rgba(255,255,255,.7);margin-top:6px">Gérez votre budget en toute sérénité</div>
        </td>
      </tr>

      <!-- Body -->
      <tr>
        <td style="padding:40px 40px 32px">
          <p style="margin:0 0 20px;font-size:22px;font-weight:600;color:#1e3a5f">
            Bienvenue, {household_name}&nbsp;! 🎉
          </p>
          <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.7">
            Merci d'avoir rejoint <strong>Budget Familial</strong>. Ton foyer est maintenant configuré et prêt à gérer vos finances en toute simplicité.
          </p>
          <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.7">
            L'application va continuer à évoluer grâce aux retours des utilisateurs comme toi. Chaque suggestion compte et contribue à rendre l'expérience meilleure pour tous les foyers.
          </p>
          <p style="margin:0 0 28px;font-size:15px;color:#374151;line-height:1.7">
            Et bonne nouvelle : <strong>Budget Familial sera bientôt disponible sur App Store et Play Store</strong> pour encore plus de praticité au quotidien. Reste connecté !
          </p>

          <!-- Astuce écran d'accueil -->
          <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:28px">
            <tr>
              <td style="background:#f0f4fa;border-left:3px solid #2563a8;border-radius:8px;padding:20px 24px">
                <p style="margin:0 0 14px;font-size:15px;font-weight:600;color:#1e3a5f">
                  📲 Astuce : ajoutez l'app sur votre écran d'accueil
                </p>
                <p style="margin:0 0 10px;font-size:13px;font-weight:600;color:#374151">🍎 iPhone (Safari)</p>
                <ol style="margin:0 0 14px;padding-left:20px;font-size:13px;color:#374151;line-height:1.8">
                  <li>Ouvrez Safari et accédez à l'application</li>
                  <li>Appuyez sur l'icône <strong>Partager</strong> (carré avec flèche ↑) en bas</li>
                  <li>Faites défiler et appuyez sur <strong>« Sur l'écran d'accueil »</strong></li>
                  <li>Appuyez sur <strong>« Ajouter »</strong> en haut à droite</li>
                </ol>
                <p style="margin:0 0 10px;font-size:13px;font-weight:600;color:#374151">🤖 Android (Chrome)</p>
                <ol style="margin:0;padding-left:20px;font-size:13px;color:#374151;line-height:1.8">
                  <li>Ouvrez Chrome et accédez à l'application</li>
                  <li>Appuyez sur les <strong>3 points</strong> en haut à droite</li>
                  <li>Appuyez sur <strong>« Ajouter à l'écran d'accueil »</strong></li>
                  <li>Confirmez en appuyant sur <strong>« Ajouter »</strong></li>
                </ol>
              </td>
            </tr>
          </table>

          <!-- CTA Guide -->
          <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:16px">
            <tr>
              <td align="center">
                <a href="https://budget-web-38nm.onrender.com/guide"
                   style="display:inline-block;background:#2563a8;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:14px 32px;border-radius:8px">
                  📖 Consulter le guide d'utilisation
                </a>
              </td>
            </tr>
          </table>

          <!-- CTA Contact -->
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr>
              <td align="center">
                <a href="https://budget-web-38nm.onrender.com/contact"
                   style="display:inline-block;background:#f8fafc;color:#2563a8;text-decoration:none;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;border:1.5px solid #2563a8">
                  ✉️ Envoyer une suggestion
                </a>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Divider -->
      <tr><td style="padding:0 40px"><hr style="border:none;border-top:1px solid #e5e7eb;margin:0"></td></tr>

      <!-- Footer -->
      <tr>
        <td style="padding:24px 40px;text-align:center">
          <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6">
            Tu reçois cet email car tu viens de créer un compte sur Budget Familial.<br>
            &copy; Anas.m — Budget Familial
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
    payload = {
        "sender": {"email": from_email, "name": "Budget Familial"},
        "to": [{"email": to_email}],
        "replyTo": {"email": "contact.budgetfamilial@gmail.com"},
        "subject": f"Bienvenue sur Budget Familial, {household_name} !",
        "htmlContent": html,
    }
    resp = _req.post(
        "https://api.brevo.com/v3/smtp/email",
        json=payload,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()


# ── Mot de passe oublié ────────────────────────────────────────────────────

def _send_reset_email(to_email, reset_url):
    import requests as _req
    api_key = os.environ.get("BREVO_API_KEY", "")
    from_email = os.environ.get("MAIL_FROM", "noreply@budget-familial.app")
    payload = {
        "sender": {"email": from_email, "name": "Budget Familial"},
        "to": [{"email": to_email}],
        "replyTo": {"email": "contact.budgetfamilial@gmail.com"},
        "subject": "Réinitialisation de ton mot de passe — Budget Familial",
        "htmlContent": (
            "<p>Bonjour,</p>"
            "<p>Tu as demandé à réinitialiser ton mot de passe.</p>"
            f'<p><a href="{reset_url}" style="color:#2563a8">Cliquer ici pour choisir un nouveau mot de passe</a></p>'
            f"<p>Ou copie ce lien dans ton navigateur :<br><code>{reset_url}</code></p>"
            "<p>Ce lien est valable <strong>1 heure</strong>. "
            "Si tu n'es pas à l'origine de cette demande, ignore cet email.</p>"
            "<p>— Budget Familial</p>"
        )
    }
    resp = _req.post(
        "https://api.brevo.com/v3/smtp/email",
        json=payload,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()


def _send_contact_notification(nom, email, telephone, message):
    import requests as _req
    api_key = os.environ.get("BREVO_API_KEY", "")
    from_email = os.environ.get("MAIL_FROM", "noreply@budget-familial.app")
    tel_line = f"<p><strong>Téléphone :</strong> {telephone}</p>" if telephone else ""
    payload = {
        "sender": {"email": from_email, "name": "Budget Familial"},
        "to": [{"email": "contact.budgetfamilial@gmail.com", "name": "Anas"}],
        "replyTo": {"email": email, "name": nom},
        "subject": f"Nouveau message de contact — {nom}",
        "htmlContent": (
            "<p>Tu as reçu un nouveau message via le formulaire de contact.</p>"
            f"<p><strong>Nom :</strong> {nom}</p>"
            f"<p><strong>Email :</strong> {email}</p>"
            f"{tel_line}"
            f"<p><strong>Message :</strong></p>"
            f"<blockquote style='border-left:3px solid #ccc;margin:0;padding:0 1em;color:#555'>{message}</blockquote>"
            "<p style='color:#999;font-size:.85em'>— Budget Familial</p>"
        )
    }
    resp = _req.post(
        "https://api.brevo.com/v3/smtp/email",
        json=payload,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = db.get_user_by_email(email)
        if user:
            token = secrets.token_urlsafe(32)
            db.create_reset_token(user["id"], token)
            reset_url = url_for("reset_password", token=token, _external=True)
            try:
                _send_reset_email(email, reset_url)
            except Exception as e:
                app.logger.error("Brevo error: %s", e)
        # Same redirect whether email exists or not (avoids user enumeration)
        return redirect(url_for("forgot_password_sent"))
    return render_template("forgot_password.html")


@app.route("/forgot-password/sent")
def forgot_password_sent():
    return render_template("forgot_password_sent.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    token_row = db.get_reset_token(token)
    if not token_row or token_row["used"]:
        flash("Lien invalide ou déjà utilisé.", "error")
        return redirect(url_for("forgot_password"))

    created_at = datetime.strptime(token_row["created_at"][:19], "%Y-%m-%d %H:%M:%S")
    if datetime.now() - created_at > timedelta(hours=1):
        flash("Ce lien a expiré. Fais une nouvelle demande.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        pwd = request.form.get("password", "")
        pwd2 = request.form.get("password2", "")
        if len(pwd) < 6:
            flash("Mot de passe trop court (6 caractères min).", "error")
            return render_template("reset_password.html", token=token)
        if pwd != pwd2:
            flash("Les mots de passe ne correspondent pas.", "error")
            return render_template("reset_password.html", token=token)
        db.update_password(token_row["user_id"], generate_password_hash(pwd))
        db.invalidate_reset_token(token)
        flash("Mot de passe mis à jour. Tu peux te connecter.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


if __name__ == "__main__":
    app.run(debug=True)

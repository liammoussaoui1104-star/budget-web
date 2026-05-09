import os
import sqlite3
import secrets
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "budget_web.db")

# Render provides postgres:// but psycopg2 needs postgresql://
_raw_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL = _raw_url.replace("postgres://", "postgresql://", 1) if _raw_url else ""

_USE_PG = bool(DATABASE_URL)
_PH = "%s" if _USE_PG else "?"

if _USE_PG:
    import psycopg2
    import psycopg2.extras

CATS = ["Loyer", "Crédits", "Assurance", "Courses", "Carburant",
        "Abonnements", "Santé", "Éducation", "Loisirs", "Restaurants",
        "Vêtements", "Cadeaux", "Divers"]

MEMBER_COLORS = ["#2563a8", "#e07a30", "#d99a3a", "#7a9968",
                 "#9b59b6", "#e74c3c", "#1abc9c", "#f39c12"]


class DB:
    # ── Connection ─────────────────────────────────────────────────────────

    def _open_conn(self):
        if _USE_PG:
            return psycopg2.connect(DATABASE_URL)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _run(self, sql, params=(), fetch=None):
        """
        Execute sql (use ? placeholders for both backends).
        fetch: None | 'one' | 'all' | 'id' (returns last inserted id)
        """
        conn = self._open_conn()
        try:
            sql_n = sql.replace("?", _PH)
            if fetch == "id" and _USE_PG:
                sql_n = sql_n.rstrip().rstrip(";") + " RETURNING id"
            if _USE_PG:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(sql_n, params or ())
            else:
                cur = conn.execute(sql_n, params or ())

            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            elif fetch == "id":
                result = cur.fetchone()["id"] if _USE_PG else cur.lastrowid
            else:
                result = None
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema ─────────────────────────────────────────────────────────────

    def _init(self):
        pk = "SERIAL PRIMARY KEY" if _USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
        ts = "DEFAULT CURRENT_TIMESTAMP" if _USE_PG else "DEFAULT (datetime('now'))"

        stmts = [
            f"""CREATE TABLE IF NOT EXISTS users (
                id {pk},
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                household_name TEXT DEFAULT '',
                is_admin INTEGER DEFAULT 0,
                created_at TEXT {ts}
            )""",
            f"""CREATE TABLE IF NOT EXISTS members (
                id {pk},
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'Payeur',
                color TEXT DEFAULT '#2563a8',
                is_payer INTEGER DEFAULT 0
            )""",
            f"""CREATE TABLE IF NOT EXISTS salaires (
                id {pk},
                user_id INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                montant REAL DEFAULT 0,
                UNIQUE(user_id, annee, mois, member_id)
            )""",
            f"""CREATE TABLE IF NOT EXISTS depenses (
                id {pk},
                user_id INTEGER NOT NULL,
                annee INTEGER NOT NULL,
                mois INTEGER NOT NULL,
                jour INTEGER NOT NULL,
                montant REAL NOT NULL,
                categorie TEXT NOT NULL,
                description TEXT DEFAULT '',
                personne TEXT NOT NULL,
                type_dep TEXT DEFAULT 'Variable',
                pour_qui TEXT DEFAULT 'Commun'
            )""",
            f"""CREATE TABLE IF NOT EXISTS budgets (
                id {pk},
                user_id INTEGER NOT NULL,
                categorie TEXT NOT NULL,
                plafond REAL DEFAULT 0,
                UNIQUE(user_id, categorie)
            )""",
            f"""CREATE TABLE IF NOT EXISTS contact_messages (
                id {pk},
                nom TEXT NOT NULL,
                email TEXT NOT NULL,
                telephone TEXT DEFAULT '',
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                lu INTEGER DEFAULT 0
            )""",
            f"""CREATE TABLE IF NOT EXISTS reset_tokens (
                id {pk},
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )""",
        ]

        conn = self._open_conn()
        try:
            if _USE_PG:
                cur = conn.cursor()
                for stmt in stmts:
                    cur.execute(stmt)
            else:
                for stmt in stmts:
                    conn.execute(stmt)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        self._migrate()

    def _migrate(self):
        """Add new columns to existing tables without breaking live databases."""
        migrations = [
            "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0",
        ]
        for sql in migrations:
            try:
                self._run(sql)
            except Exception:
                pass  # column already exists

    def __init__(self):
        self._init()

    # ── Users ──────────────────────────────────────────────────────────────

    def create_user(self, email, password_hash, household_name=""):
        try:
            return self._run(
                "INSERT INTO users (email, password_hash, household_name) VALUES (?,?,?)",
                (email, password_hash, household_name),
                fetch="id"
            )
        except Exception:
            return None

    def get_user_by_email(self, email):
        return self._run("SELECT * FROM users WHERE email=?", (email,), fetch="one")

    def get_user_by_id(self, uid):
        return self._run("SELECT * FROM users WHERE id=?", (uid,), fetch="one")

    def update_household_name(self, uid, name):
        self._run("UPDATE users SET household_name=? WHERE id=?", (name, uid))

    def update_password(self, uid, password_hash):
        self._run("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))

    # ── Members ────────────────────────────────────────────────────────────

    def get_members(self, uid):
        return self._run(
            "SELECT * FROM members WHERE user_id=? ORDER BY id", (uid,), fetch="all"
        )

    def get_payers(self, uid):
        return self._run(
            "SELECT * FROM members WHERE user_id=? AND is_payer=1 ORDER BY id",
            (uid,), fetch="all"
        )

    def add_member(self, uid, name, role, is_payer, color):
        return self._run(
            "INSERT INTO members (user_id, name, role, color, is_payer) VALUES (?,?,?,?,?)",
            (uid, name, role, color, 1 if is_payer else 0),
            fetch="id"
        )

    def delete_all_members(self, uid):
        self._run("DELETE FROM members WHERE user_id=?", (uid,))

    def get_member_by_name(self, uid, name):
        return self._run(
            "SELECT * FROM members WHERE user_id=? AND name=?", (uid, name), fetch="one"
        )

    # ── Salaires ───────────────────────────────────────────────────────────

    def get_salaires(self, uid, y, m):
        rows = self._run("""
            SELECT s.montant, mem.name, mem.id as member_id
            FROM salaires s JOIN members mem ON s.member_id=mem.id
            WHERE s.user_id=? AND s.annee=? AND s.mois=?
        """, (uid, y, m), fetch="all")
        return {r["name"]: r["montant"] for r in rows}

    def save_salaire(self, uid, y, m, member_id, montant):
        self._run("""
            INSERT INTO salaires (user_id, annee, mois, member_id, montant)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id, annee, mois, member_id)
            DO UPDATE SET montant=excluded.montant
        """, (uid, y, m, member_id, montant))

    def get_total_revenus(self, uid, y, m):
        row = self._run(
            "SELECT COALESCE(SUM(montant),0) as total FROM salaires WHERE user_id=? AND annee=? AND mois=?",
            (uid, y, m), fetch="one"
        )
        return row["total"]

    def reset_salaire(self, uid, y, m, member_id):
        self._run(
            "DELETE FROM salaires WHERE user_id=? AND annee=? AND mois=? AND member_id=?",
            (uid, y, m, member_id)
        )

    # ── Dépenses ───────────────────────────────────────────────────────────

    def add_depense(self, uid, annee, mois, jour, montant, categorie, description, personne, type_dep, pour_qui):
        return self._run("""
            INSERT INTO depenses (user_id, annee, mois, jour, montant, categorie, description, personne, type_dep, pour_qui)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (uid, annee, mois, jour, montant, categorie, description, personne, type_dep, pour_qui),
            fetch="id"
        )

    def get_depenses(self, uid, y, m):
        return self._run("""
            SELECT * FROM depenses WHERE user_id=? AND annee=? AND mois=?
            ORDER BY jour DESC, id DESC
        """, (uid, y, m), fetch="all")

    def get_depense_by_id(self, uid, dep_id):
        return self._run(
            "SELECT * FROM depenses WHERE id=? AND user_id=?", (dep_id, uid), fetch="one"
        )

    def update_depense(self, uid, dep_id, jour, montant, categorie, description, personne, type_dep, pour_qui):
        self._run("""
            UPDATE depenses SET jour=?, montant=?, categorie=?, description=?,
            personne=?, type_dep=?, pour_qui=?
            WHERE id=? AND user_id=?
        """, (jour, montant, categorie, description, personne, type_dep, pour_qui, dep_id, uid))

    def delete_depense(self, uid, dep_id):
        self._run("DELETE FROM depenses WHERE id=? AND user_id=?", (dep_id, uid))

    def get_last_depenses(self, uid, y, m, limit=10):
        return self._run("""
            SELECT * FROM depenses WHERE user_id=? AND annee=? AND mois=?
            ORDER BY jour DESC, id DESC LIMIT ?
        """, (uid, y, m, limit), fetch="all")

    def has_depenses(self, uid, y, m):
        row = self._run(
            "SELECT COUNT(*) as c FROM depenses WHERE user_id=? AND annee=? AND mois=?",
            (uid, y, m), fetch="one"
        )
        return row["c"] > 0

    # ── Agrégats dépenses ──────────────────────────────────────────────────

    def get_totaux_payeur(self, uid, y, m):
        rows = self._run("""
            SELECT personne, COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=?
            GROUP BY personne
        """, (uid, y, m), fetch="all")
        return {r["personne"]: r["total"] for r in rows}

    def get_totaux_pour(self, uid, y, m):
        rows = self._run("""
            SELECT pour_qui, COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=?
            GROUP BY pour_qui
        """, (uid, y, m), fetch="all")
        return {r["pour_qui"]: r["total"] for r in rows}

    def get_totaux_cat(self, uid, y, m):
        rows = self._run("""
            SELECT categorie, COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=?
            GROUP BY categorie
        """, (uid, y, m), fetch="all")
        return {r["categorie"]: r["total"] for r in rows}

    def get_totaux_cat_par_payeur(self, uid, y, m):
        rows = self._run("""
            SELECT categorie, personne, COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=?
            GROUP BY categorie, personne
        """, (uid, y, m), fetch="all")
        result = {}
        for r in rows:
            result.setdefault(r["categorie"], {})[r["personne"]] = r["total"]
        return result

    def get_fixes_par_payeur(self, uid, y, m):
        rows = self._run("""
            SELECT personne, COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
            GROUP BY personne
        """, (uid, y, m), fetch="all")
        return {r["personne"]: r["total"] for r in rows}

    def get_fixes_commun(self, uid, y, m):
        row = self._run("""
            SELECT COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=?
            AND type_dep='Fixe' AND pour_qui='Commun'
        """, (uid, y, m), fetch="one")
        return row["total"]

    def get_fixes_manquantes(self, uid, src_y, src_m, tgt_y, tgt_m):
        src_cats = self._run("""
            SELECT categorie FROM depenses
            WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
        """, (uid, src_y, src_m), fetch="all")
        src_set = {r["categorie"] for r in src_cats}

        tgt_cats = self._run("""
            SELECT categorie FROM depenses
            WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
        """, (uid, tgt_y, tgt_m), fetch="all")
        tgt_set = {r["categorie"] for r in tgt_cats}

        missing = src_set - tgt_set
        if not missing:
            return []

        placeholders = ",".join(["?"] * len(missing))
        return self._run("""
            SELECT * FROM depenses
            WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
            AND categorie IN ({})
        """.format(placeholders),
            [uid, src_y, src_m] + list(missing),
            fetch="all"
        )

    def reconduire_fixes(self, uid, src_y, src_m, tgt_y, tgt_m):
        rows = self.get_fixes_manquantes(uid, src_y, src_m, tgt_y, tgt_m)
        count = 0
        for r in rows:
            self.add_depense(
                uid, tgt_y, tgt_m, r["jour"], r["montant"],
                r["categorie"], r["description"], r["personne"],
                r["type_dep"], r["pour_qui"]
            )
            count += 1
        return count

    def get_total_by_type(self, uid, y, m, type_dep):
        row = self._run("""
            SELECT COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=? AND type_dep=?
        """, (uid, y, m, type_dep), fetch="one")
        return row["total"]

    # ── Budgets ────────────────────────────────────────────────────────────

    def get_budgets(self, uid):
        rows = self._run(
            "SELECT categorie, plafond FROM budgets WHERE user_id=?", (uid,), fetch="all"
        )
        return {r["categorie"]: r["plafond"] for r in rows}

    def set_budget(self, uid, categorie, plafond):
        self._run("""
            INSERT INTO budgets (user_id, categorie, plafond) VALUES (?,?,?)
            ON CONFLICT(user_id, categorie) DO UPDATE SET plafond=excluded.plafond
        """, (uid, categorie, plafond))

    # ── Contact messages ───────────────────────────────────────────────────

    def add_contact_message(self, nom, email, telephone, message):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._run(
            "INSERT INTO contact_messages (nom, email, telephone, message, created_at) VALUES (?,?,?,?,?)",
            (nom, email, telephone, message, now)
        )

    def get_contact_messages(self):
        return self._run(
            "SELECT * FROM contact_messages ORDER BY created_at DESC", fetch="all"
        )

    def mark_message_lu(self, msg_id):
        self._run("UPDATE contact_messages SET lu=1 WHERE id=?", (msg_id,))

    # ── Reset tokens ───────────────────────────────────────────────────────

    def create_reset_token(self, user_id, token):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Invalidate any previous tokens for this user
        self._run("UPDATE reset_tokens SET used=1 WHERE user_id=?", (user_id,))
        self._run(
            "INSERT INTO reset_tokens (user_id, token, created_at) VALUES (?,?,?)",
            (user_id, token, now)
        )

    def get_reset_token(self, token):
        return self._run(
            "SELECT * FROM reset_tokens WHERE token=?", (token,), fetch="one"
        )

    def invalidate_reset_token(self, token):
        self._run("UPDATE reset_tokens SET used=1 WHERE token=?", (token,))

    # ── Utils ──────────────────────────────────────────────────────────────

    def get_totaux_pour_member(self, uid, y, m, member_name):
        row = self._run("""
            SELECT COALESCE(SUM(montant),0) as total
            FROM depenses WHERE user_id=? AND annee=? AND mois=? AND pour_qui=?
        """, (uid, y, m, member_name), fetch="one")
        return row["total"]

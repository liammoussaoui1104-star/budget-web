import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "budget_web.db")

CATS = ["Loyer", "Crédits", "Assurance", "Courses", "Carburant",
        "Abonnements", "Santé", "Éducation", "Loisirs", "Restaurants",
        "Vêtements", "Cadeaux", "Divers"]

MEMBER_COLORS = ["#2563a8", "#e07a30", "#d99a3a", "#7a9968",
                 "#9b59b6", "#e74c3c", "#1abc9c", "#f39c12"]


class DB:
    def __init__(self):
        self.path = DB_PATH
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    household_name TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT DEFAULT 'Payeur',
                    color TEXT DEFAULT '#2563a8',
                    is_payer INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS salaires (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    annee INTEGER NOT NULL,
                    mois INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    montant REAL DEFAULT 0,
                    UNIQUE(user_id, annee, mois, member_id),
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (member_id) REFERENCES members(id)
                );
                CREATE TABLE IF NOT EXISTS depenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    annee INTEGER NOT NULL,
                    mois INTEGER NOT NULL,
                    jour INTEGER NOT NULL,
                    montant REAL NOT NULL,
                    categorie TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    personne TEXT NOT NULL,
                    type_dep TEXT DEFAULT 'Variable',
                    pour_qui TEXT DEFAULT 'Commun',
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    categorie TEXT NOT NULL,
                    plafond REAL DEFAULT 0,
                    UNIQUE(user_id, categorie),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            """)

    # ── Users ──────────────────────────────────────────────────────────────
    def create_user(self, email, password_hash, household_name=""):
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, household_name) VALUES (?,?,?)",
                    (email, password_hash, household_name)
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def get_user_by_email(self, email):
        with self._conn() as conn:
            return conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

    def get_user_by_id(self, uid):
        with self._conn() as conn:
            return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def update_household_name(self, uid, name):
        with self._conn() as conn:
            conn.execute("UPDATE users SET household_name=? WHERE id=?", (name, uid))

    # ── Members ────────────────────────────────────────────────────────────
    def get_members(self, uid):
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM members WHERE user_id=? ORDER BY id", (uid,)
            ).fetchall()

    def get_payers(self, uid):
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM members WHERE user_id=? AND is_payer=1 ORDER BY id", (uid,)
            ).fetchall()

    def add_member(self, uid, name, role, is_payer, color):
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO members (user_id, name, role, color, is_payer) VALUES (?,?,?,?,?)",
                (uid, name, role, color, 1 if is_payer else 0)
            )
            return cur.lastrowid

    def delete_all_members(self, uid):
        with self._conn() as conn:
            conn.execute("DELETE FROM members WHERE user_id=?", (uid,))

    def get_member_by_name(self, uid, name):
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM members WHERE user_id=? AND name=?", (uid, name)
            ).fetchone()

    # ── Salaires ───────────────────────────────────────────────────────────
    def get_salaires(self, uid, y, m):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT s.montant, mem.name, mem.id as member_id
                FROM salaires s JOIN members mem ON s.member_id=mem.id
                WHERE s.user_id=? AND s.annee=? AND s.mois=?
            """, (uid, y, m)).fetchall()
        return {r["name"]: r["montant"] for r in rows}

    def save_salaire(self, uid, y, m, member_id, montant):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO salaires (user_id, annee, mois, member_id, montant)
                VALUES (?,?,?,?,?)
                ON CONFLICT(user_id, annee, mois, member_id)
                DO UPDATE SET montant=excluded.montant
            """, (uid, y, m, member_id, montant))

    def get_total_revenus(self, uid, y, m):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(montant),0) as total FROM salaires WHERE user_id=? AND annee=? AND mois=?",
                (uid, y, m)
            ).fetchone()
        return row["total"]

    # ── Dépenses ───────────────────────────────────────────────────────────
    def add_depense(self, uid, annee, mois, jour, montant, categorie, description, personne, type_dep, pour_qui):
        with self._conn() as conn:
            cur = conn.execute("""
                INSERT INTO depenses (user_id, annee, mois, jour, montant, categorie, description, personne, type_dep, pour_qui)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (uid, annee, mois, jour, montant, categorie, description, personne, type_dep, pour_qui))
            return cur.lastrowid

    def get_depenses(self, uid, y, m):
        with self._conn() as conn:
            return conn.execute("""
                SELECT * FROM depenses WHERE user_id=? AND annee=? AND mois=?
                ORDER BY jour DESC, id DESC
            """, (uid, y, m)).fetchall()

    def get_depense_by_id(self, uid, dep_id):
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM depenses WHERE id=? AND user_id=?", (dep_id, uid)
            ).fetchone()

    def update_depense(self, uid, dep_id, jour, montant, categorie, description, personne, type_dep, pour_qui):
        with self._conn() as conn:
            conn.execute("""
                UPDATE depenses SET jour=?, montant=?, categorie=?, description=?,
                personne=?, type_dep=?, pour_qui=?
                WHERE id=? AND user_id=?
            """, (jour, montant, categorie, description, personne, type_dep, pour_qui, dep_id, uid))

    def delete_depense(self, uid, dep_id):
        with self._conn() as conn:
            conn.execute("DELETE FROM depenses WHERE id=? AND user_id=?", (dep_id, uid))

    def get_last_depenses(self, uid, y, m, limit=10):
        with self._conn() as conn:
            return conn.execute("""
                SELECT * FROM depenses WHERE user_id=? AND annee=? AND mois=?
                ORDER BY jour DESC, id DESC LIMIT ?
            """, (uid, y, m, limit)).fetchall()

    def has_depenses(self, uid, y, m):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM depenses WHERE user_id=? AND annee=? AND mois=?",
                (uid, y, m)
            ).fetchone()
        return row["c"] > 0

    # ── Agrégats dépenses ──────────────────────────────────────────────────
    def get_totaux_payeur(self, uid, y, m):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT personne, COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=?
                GROUP BY personne
            """, (uid, y, m)).fetchall()
        return {r["personne"]: r["total"] for r in rows}

    def get_totaux_pour(self, uid, y, m):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT pour_qui, COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=?
                GROUP BY pour_qui
            """, (uid, y, m)).fetchall()
        return {r["pour_qui"]: r["total"] for r in rows}

    def get_totaux_cat(self, uid, y, m):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT categorie, COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=?
                GROUP BY categorie
            """, (uid, y, m)).fetchall()
        return {r["categorie"]: r["total"] for r in rows}

    def get_totaux_cat_par_payeur(self, uid, y, m):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT categorie, personne, COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=?
                GROUP BY categorie, personne
            """, (uid, y, m)).fetchall()
        result = {}
        for r in rows:
            result.setdefault(r["categorie"], {})[r["personne"]] = r["total"]
        return result

    def get_fixes_par_payeur(self, uid, y, m):
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT personne, COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
                GROUP BY personne
            """, (uid, y, m)).fetchall()
        return {r["personne"]: r["total"] for r in rows}

    def get_fixes_commun(self, uid, y, m):
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=?
                AND type_dep='Fixe' AND pour_qui='Commun'
            """, (uid, y, m)).fetchone()
        return row["total"]

    def get_fixes_manquantes(self, uid, src_y, src_m, tgt_y, tgt_m):
        with self._conn() as conn:
            src_cats = conn.execute("""
                SELECT categorie FROM depenses
                WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
            """, (uid, src_y, src_m)).fetchall()
            src_set = {r["categorie"] for r in src_cats}

            tgt_cats = conn.execute("""
                SELECT categorie FROM depenses
                WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
            """, (uid, tgt_y, tgt_m)).fetchall()
            tgt_set = {r["categorie"] for r in tgt_cats}

            missing = src_set - tgt_set
            if not missing:
                return []

            rows = conn.execute("""
                SELECT * FROM depenses
                WHERE user_id=? AND annee=? AND mois=? AND type_dep='Fixe'
                AND categorie IN ({})
            """.format(",".join("?" * len(missing))),
                [uid, src_y, src_m] + list(missing)
            ).fetchall()
        return rows

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
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=? AND type_dep=?
            """, (uid, y, m, type_dep)).fetchone()
        return row["total"]

    # ── Budgets ────────────────────────────────────────────────────────────
    def get_budgets(self, uid):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT categorie, plafond FROM budgets WHERE user_id=?", (uid,)
            ).fetchall()
        return {r["categorie"]: r["plafond"] for r in rows}

    def set_budget(self, uid, categorie, plafond):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO budgets (user_id, categorie, plafond) VALUES (?,?,?)
                ON CONFLICT(user_id, categorie) DO UPDATE SET plafond=excluded.plafond
            """, (uid, categorie, plafond))

    def reset_salaire(self, uid, y, m, member_id):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM salaires WHERE user_id=? AND annee=? AND mois=? AND member_id=?",
                (uid, y, m, member_id)
            )

    def get_totaux_pour_member(self, uid, y, m, member_name):
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(SUM(montant),0) as total
                FROM depenses WHERE user_id=? AND annee=? AND mois=? AND pour_qui=?
            """, (uid, y, m, member_name)).fetchone()
        return row["total"]

import csv
import hmac
import io
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from werkzeug.exceptions import HTTPException

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TIMEZONE = ZoneInfo("Africa/Abidjan")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
# Une lettre, puis lettres, espaces, tirets, apostrophes ou points : « N'Guessan », « Jean-David ».
NOM_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '.\-])*$")
NOM_MAX = 80
MOTIF_MAX = 300
IMPORT_MAX_LIGNES = 500
MAX_ECHECS_CONNEXION = 10
FENETRE_ECHECS = timedelta(minutes=15)
FORMAT_MOMENT = "%Y-%m-%d %H:%M:%S"

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
SESSION_SECRET = os.environ.get("SESSION_SECRET")
# Postgres dès qu'une URL est fournie (production), SQLite sinon (développement local).
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
SQLITE_PATH = os.environ.get("SQLITE_PATH") or os.path.join(BASE_DIR, "pointage.db")
# Un second scan trop proche de l'arrivée (double appui, doute « est-ce que ça a marché ? »)
# ne doit pas enregistrer le départ : la journée serait close pour de bon.
DELAI_MIN_DEPART = timedelta(minutes=int(os.environ.get("DELAI_MIN_DEPART_MINUTES") or 30))
SUR_VERCEL = bool(os.environ.get("VERCEL"))

if not ADMIN_PASSWORD or not SESSION_SECRET:
    raise RuntimeError(
        "ADMIN_PASSWORD et SESSION_SECRET doivent être définis : copier .env.example en .env "
        "en local, ou les ajouter aux variables d'environnement du projet Vercel.")
if SUR_VERCEL:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL manquante. Le disque des fonctions Vercel n'est pas persistant : "
            "un fichier SQLite y perdrait les pointages. Connecter une base Postgres (Neon) au projet.")
    if len(SESSION_SECRET) < 32 or len(ADMIN_PASSWORD) < 12:
        raise RuntimeError(
            "En production, SESSION_SECRET doit compter au moins 32 caractères "
            "et ADMIN_PASSWORD au moins 12.")

app = Flask(__name__, static_folder="public/static", static_url_path="/static")
app.config.update(
    SECRET_KEY=SESSION_SECRET,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SUR_VERCEL,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=512 * 1024,
)

CSP = (
    "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
MESSAGES_HTTP = {
    404: "Adresse inconnue.",
    405: "Méthode non autorisée.",
    413: "Requête trop volumineuse.",
    500: "Erreur interne du serveur.",
}

_schema_pret = False


def get_db():
    """Une connexion par requête, fermée en fin de requête."""
    global _schema_pret
    if "db" not in g:
        if DATABASE_URL:
            # Importé ici : le développement local sur SQLite n'en a pas besoin.
            import psycopg
            from psycopg.rows import dict_row
            g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            g.db = sqlite3.connect(SQLITE_PATH)
            g.db.row_factory = sqlite3.Row
        if not _schema_pret:
            creer_schema(g.db)
            _schema_pret = True
    return g.db


@app.teardown_appcontext
def fermer_db(_exception):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def creer_schema(conn):
    if DATABASE_URL:
        # Deux instances qui démarrent en même temps ne doivent pas créer les tables ensemble.
        conn.execute("SELECT pg_advisory_xact_lock(718324)")
        colonne_id = "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    else:
        colonne_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS pointages (
            id {colonne_id},
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            date TEXT NOT NULL,
            heure_arrivee TEXT,
            heure_depart TEXT,
            motif TEXT,
            source TEXT NOT NULL DEFAULT 'auto',
            UNIQUE(nom, prenom, date))""")
    if not DATABASE_URL:
        # Bases SQLite créées avant l'ajout des colonnes motif et source.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(pointages)").fetchall()}
        if "motif" not in existing_cols:
            conn.execute("ALTER TABLE pointages ADD COLUMN motif TEXT")
        if "source" not in existing_cols:
            conn.execute("ALTER TABLE pointages ADD COLUMN source TEXT NOT NULL DEFAULT 'auto'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pointages_date ON pointages (date)")
    conn.execute("CREATE TABLE IF NOT EXISTS tentatives_connexion (ip TEXT NOT NULL, moment TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tentatives_ip ON tentatives_connexion (ip)")
    conn.commit()


def executer(sql, params=()):
    """Les requêtes s'écrivent avec des « ? », convertis en « %s » pour Postgres."""
    if DATABASE_URL:
        return get_db().execute(sql.replace("?", "%s"), params or None)
    return get_db().execute(sql, params)


def lignes(sql, params=()):
    return [dict(row) for row in executer(sql, params).fetchall()]


def maintenant():
    return datetime.now(TIMEZONE)


def corps_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def nettoyer(texte):
    """Espaces superflus retirés ; l'apostrophe typographique des claviers de téléphone devient « ' »."""
    texte = unicodedata.normalize("NFC", str(texte or "")).replace("’", "'")
    return " ".join(texte.split())


def formater_nom(nom):
    return nettoyer(nom).upper()


def formater_prenom(prenom):
    return re.sub(r"[^\s'\-]+", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), nettoyer(prenom))


def cle_personne(nom, prenom):
    """Clé de rapprochement insensible à la casse, aux accents et à la ponctuation :
    « Éclésiaste » le matin et « ECLESIASTE » le soir désignent la même personne."""
    def cle(texte):
        return "".join(c for c in unicodedata.normalize("NFKD", texte.casefold()) if c.isalpha())
    return cle(nom), cle(prenom)


def erreur_identite(nom, prenom):
    if not nom or not prenom:
        return "Nom et prénom requis."
    if len(nom) > NOM_MAX or len(prenom) > NOM_MAX:
        return f"Nom et prénom sont limités à {NOM_MAX} caractères."
    if not NOM_RE.match(nom) or not NOM_RE.match(prenom):
        return "Nom et prénom ne peuvent contenir que des lettres, espaces, tirets et apostrophes."
    return None


def trouver_pointage(date_str, nom, prenom):
    cle = cle_personne(nom, prenom)
    for ligne in lignes("SELECT * FROM pointages WHERE date = ?", (date_str,)):
        if cle_personne(ligne["nom"], ligne["prenom"]) == cle:
            return ligne
    return None


def admin_requis(vue):
    @wraps(vue)
    def verifiee(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "Non autorisé."}), 401
        return vue(*args, **kwargs)
    return verifiee


@app.after_request
def entetes_securite(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", CSP)
    if request.path.startswith(("/api/", "/admin/")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(HTTPException)
def erreur_http(e):
    if not request.path.startswith(("/api/", "/admin/")):
        return e
    personnalise = e.description != type(e).description
    message = e.description if personnalise else MESSAGES_HTTP.get(e.code, e.name)
    return jsonify({"error": message}), e.code


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/api/pointage", methods=["POST"])
def pointage():
    data = corps_json()
    nom = formater_nom(data.get("nom"))
    prenom = formater_prenom(data.get("prenom"))
    erreur = erreur_identite(nom, prenom)
    if erreur:
        return jsonify({"error": erreur}), 400

    now = maintenant()
    date_str, heure = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    existing = trouver_pointage(date_str, nom, prenom)

    if existing is None:
        insertion = executer(
            "INSERT INTO pointages (nom, prenom, date, heure_arrivee) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (nom, prenom, date_str, heure))
        get_db().commit()
        if insertion.rowcount == 1:
            return jsonify({"type": "arrivee", "nom": nom, "prenom": prenom, "date": date_str, "heure": heure})
        # Une requête simultanée (double appui) vient d'enregistrer l'arrivée.
        existing = trouver_pointage(date_str, nom, prenom)
        if existing is None:
            return jsonify({"error": "Pointage impossible, réessayez."}), 409

    identite = {"nom": existing["nom"], "prenom": existing["prenom"], "date": date_str}

    if existing["heure_depart"] is None:
        if existing["heure_arrivee"]:
            arrivee = datetime.combine(now.date(), time.fromisoformat(existing["heure_arrivee"]), TIMEZONE)
            depart_possible = arrivee + DELAI_MIN_DEPART
            if now < depart_possible:
                return jsonify({
                    **identite,
                    "type": "deja_arrive",
                    "heure_arrivee": existing["heure_arrivee"],
                    "depart_possible": depart_possible.strftime("%H:%M")})
        executer("UPDATE pointages SET heure_depart = ? WHERE id = ? AND heure_depart IS NULL", (heure, existing["id"]))
        get_db().commit()
        return jsonify({**identite, "type": "depart", "heure": heure})

    return jsonify({
        **identite,
        "type": "deja_complet",
        "heure_arrivee": existing["heure_arrivee"],
        "heure_depart": existing["heure_depart"]})


def adresse_client():
    # Sur Vercel, x-forwarded-for est réécrit par la plateforme et porte l'IP réelle du client.
    if SUR_VERCEL:
        transmise = request.headers.get("X-Forwarded-For", "")
        if transmise:
            return transmise.split(",")[0].strip()
    return request.remote_addr or "inconnue"


@app.route("/admin/login", methods=["POST"])
def admin_login():
    ip = adresse_client()
    now_utc = datetime.now(timezone.utc)
    executer("DELETE FROM tentatives_connexion WHERE moment < ?", ((now_utc - FENETRE_ECHECS).strftime(FORMAT_MOMENT),))
    echecs = lignes("SELECT COUNT(*) AS n FROM tentatives_connexion WHERE ip = ?", (ip,))[0]["n"]
    if echecs >= MAX_ECHECS_CONNEXION:
        get_db().commit()
        minutes = int(FENETRE_ECHECS.total_seconds() // 60)
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {minutes} minutes."}), 429

    password = corps_json().get("password")
    if isinstance(password, str) and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        executer("DELETE FROM tentatives_connexion WHERE ip = ?", (ip,))
        get_db().commit()
        session.clear()
        session.permanent = True
        session["is_admin"] = True
        return jsonify({"success": True})

    executer("INSERT INTO tentatives_connexion (ip, moment) VALUES (?, ?)", (ip, now_utc.strftime(FORMAT_MOMENT)))
    get_db().commit()
    return jsonify({"error": "Mot de passe incorrect."}), 401


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/admin/status")
def admin_status():
    return jsonify({"is_admin": bool(session.get("is_admin"))})


def lire_date(valeur):
    if not DATE_RE.match(valeur):
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def lire_filtre_date():
    valeur = (request.args.get("date") or "").strip()
    if valeur and lire_date(valeur) is None:
        abort(400, "Date invalide (format attendu : AAAA-MM-JJ).")
    return valeur or None


def fetch_pointages(date_filter=None):
    if date_filter:
        return lignes("SELECT * FROM pointages WHERE date = ? ORDER BY heure_arrivee, nom, prenom", (date_filter,))
    return lignes("SELECT * FROM pointages ORDER BY date DESC, heure_arrivee, nom, prenom")


@app.route("/api/pointages")
@admin_requis
def list_pointages():
    return jsonify(fetch_pointages(lire_filtre_date()))


def normalize_heure(value):
    value = str(value or "").strip()
    if not value or not TIME_RE.match(value):
        return None
    value = value if len(value) == 8 else f"{value}:00"
    try:
        time.fromisoformat(value)
    except ValueError:
        return None
    return value


@app.route("/api/pointages/import", methods=["POST"])
@admin_requis
def import_pointages():
    """
    Report manuel de pointages antérieurs à la mise en service de l'app
    (registre papier). Chaque ligne devient un pointage source='manuel'.
    Volontairement, aucune route de modification/suppression n'existe pour
    les pointages : une fois importée, une ligne est définitive."""
    entries = corps_json().get("entries")
    if not isinstance(entries, list) or not entries:
        abort(400, "Aucune ligne à importer.")
    if len(entries) > IMPORT_MAX_LIGNES:
        abort(400, f"{IMPORT_MAX_LIGNES} lignes au maximum par import.")

    aujourd_hui = maintenant().date()
    inserted, skipped = [], []
    for i, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            skipped.append({"ligne": i, "raison": "Ligne illisible."})
            continue
        nom = formater_nom(entry.get("nom"))
        prenom = formater_prenom(entry.get("prenom"))
        date_str = nettoyer(entry.get("date"))
        heure_arrivee = normalize_heure(entry.get("heure_arrivee"))
        heure_depart = normalize_heure(entry.get("heure_depart"))
        motif = nettoyer(entry.get("motif")) or None
        jour = lire_date(date_str)

        raison = None
        if not nom or not prenom or not date_str or not entry.get("heure_arrivee"):
            raison = "Nom, prénom, date et heure d'arrivée sont requis."
        elif erreur_identite(nom, prenom):
            raison = erreur_identite(nom, prenom)
        elif jour is None:
            raison = "Date invalide (format attendu : AAAA-MM-JJ)."
        elif jour > aujourd_hui:
            raison = "La date est dans le futur."
        elif heure_arrivee is None:
            raison = "Heure d'arrivée invalide (format attendu : HH:MM)."
        elif entry.get("heure_depart") and heure_depart is None:
            raison = "Heure de départ invalide (format attendu : HH:MM)."
        elif heure_depart and heure_depart < heure_arrivee:
            raison = "L'heure de départ précède l'heure d'arrivée."
        elif motif and len(motif) > MOTIF_MAX:
            raison = f"Le motif est limité à {MOTIF_MAX} caractères."
        elif trouver_pointage(date_str, nom, prenom):
            raison = "Un pointage existe déjà pour ce nom à cette date."
        if raison:
            skipped.append({"ligne": i, "raison": raison})
            continue

        # ON CONFLICT plutôt qu'une IntegrityError : sous Postgres, une erreur annulerait tout l'import.
        insertion = executer(
            """
            INSERT INTO pointages (nom, prenom, date, heure_arrivee, heure_depart, motif, source)
            VALUES (?, ?, ?, ?, ?, ?, 'manuel') ON CONFLICT DO NOTHING""",
            (nom, prenom, date_str, heure_arrivee, heure_depart, motif))
        if insertion.rowcount == 1:
            inserted.append({"ligne": i, "nom": nom, "prenom": prenom, "date": date_str})
        else:
            skipped.append({"ligne": i, "raison": "Un pointage existe déjà pour ce nom à cette date."})

    get_db().commit()
    return jsonify({"inserted": inserted, "skipped": skipped})


def cellule_csv(valeur):
    """Un texte commençant par « = », « + », « - » ou « @ » s'exécuterait comme une formule dans Excel."""
    texte = "" if valeur is None else str(valeur)
    return f"'{texte}" if texte[:1] in ("=", "+", "-", "@", "\t", "\r") else texte


@app.route("/api/export")
@admin_requis
def export_csv():
    date_filter = lire_filtre_date()
    rows = fetch_pointages(date_filter)
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Nom", "Prenom", "Date", "Heure arrivee", "Heure depart", "Motif", "Source"])
    for r in rows:
        writer.writerow([
            cellule_csv(r[colonne])
            for colonne in ("nom", "prenom", "date", "heure_arrivee", "heure_depart", "motif", "source")])

    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    filename = f"pointages_{date_filter or 'tous'}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

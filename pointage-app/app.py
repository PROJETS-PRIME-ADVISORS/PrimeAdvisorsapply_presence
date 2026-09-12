import csv
import io
import os
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template, request, send_file, session
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "pointage.db")
TIMEZONE = ZoneInfo("Africa/Abidjan")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "change-this-secret")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pointages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            prenom TEXT NOT NULL,
            date TEXT NOT NULL,
            heure_arrivee TEXT,
            heure_depart TEXT,
            motif TEXT,
            source TEXT NOT NULL DEFAULT 'auto',
            UNIQUE(nom, prenom, date))""")  
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(pointages)").fetchall()}
    if "motif" not in existing_cols:
        conn.execute("ALTER TABLE pointages ADD COLUMN motif TEXT")
    if "source" not in existing_cols:
        conn.execute("ALTER TABLE pointages ADD COLUMN source TEXT NOT NULL DEFAULT 'auto'")
    conn.commit()
    conn.close()

def now_date_heure():
    now = datetime.now(TIMEZONE)
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")

def is_admin():
    return session.get("is_admin", False)

def fetch_pointages(date_filter=None):
    conn = get_db()
    if date_filter:
        rows = conn.execute("SELECT * FROM pointages WHERE date = ? ORDER BY heure_arrivee",
            (date_filter,),).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pointages ORDER BY date DESC, heure_arrivee").fetchall()
    conn.close()
    return rows

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/admin")
def admin_page():
    return render_template("admin.html")

@app.route("/api/pointage", methods=["POST"])
def pointage():
    data = request.get_json(silent=True) or {}
    nom = (data.get("nom") or "").strip()
    prenom = (data.get("prenom") or "").strip()

    if not nom or not prenom:
        return jsonify({"error": "Nom et prénom requis."}), 400

    date_str, heure = now_date_heure()
    conn = get_db()
    existing = conn.execute(
        """
        SELECT * FROM pointages
        WHERE LOWER(nom) = LOWER(?) AND LOWER(prenom) = LOWER(?) AND date = ?
        """,(nom, prenom, date_str),).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO pointages (nom, prenom, date, heure_arrivee) VALUES (?, ?, ?, ?)",
            (nom, prenom, date_str, heure),)
        conn.commit()
        conn.close()
        return jsonify(
            {"type": "arrivee", "nom": nom, "prenom": prenom, "date": date_str, "heure": heure})

    if existing["heure_depart"] is None:
        conn.execute("UPDATE pointages SET heure_depart = ? WHERE id = ?", (heure, existing["id"]))
        conn.commit()
        conn.close()
        return jsonify({"type": "depart", "nom": nom, "prenom": prenom, "date": date_str, "heure": heure})

    conn.close()
    return jsonify(
        {
            "type": "deja_complet",
            "nom": nom,
            "prenom": prenom,
            "date": date_str,
            "heure_arrivee": existing["heure_arrivee"],
            "heure_depart": existing["heure_depart"],})

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    if data.get("password") == ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify({"success": True})
    return jsonify({"error": "Mot de passe incorrect."}), 401

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"success": True})

@app.route("/admin/status")
def admin_status():
    return jsonify({"is_admin": is_admin()})

@app.route("/api/pointages")
def list_pointages():
    if not is_admin():
        return jsonify({"error": "Non autorisé."}), 401
    rows = fetch_pointages(request.args.get("date"))
    return jsonify([dict(r) for r in rows])

def normalize_heure(value):
    value = (value or "").strip()
    if not value:
        return None
    if not TIME_RE.match(value):
        return None
    return value if len(value) == 8 else f"{value}:00"

@app.route("/api/pointages/import", methods=["POST"])
def import_pointages():
    """
    Report manuel de pointages antérieurs à la mise en service de l'app
    (registre papier). Chaque ligne devient un pointage source='manuel'.
    Volontairement, aucune route de modification/suppression n'existe pour
    les pointages : une fois importée, une ligne est définitive."""
    if not is_admin():
        return jsonify({"error": "Non autorisé."}), 401

    data = request.get_json(silent=True) or {}
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Aucune ligne à importer."}), 400

    inserted, skipped = [], []
    conn = get_db()
    for i, entry in enumerate(entries, start=1):
        nom = (entry.get("nom") or "").strip()
        prenom = (entry.get("prenom") or "").strip()
        date_str = (entry.get("date") or "").strip()
        heure_arrivee = normalize_heure(entry.get("heure_arrivee"))
        heure_depart = normalize_heure(entry.get("heure_depart"))
        motif = (entry.get("motif") or "").strip() or None

        if not nom or not prenom or not date_str or not heure_arrivee:
            skipped.append({"ligne": i, "raison": "Nom, prénom, date et heure d'arrivée sont requis."})
            continue
        if not DATE_RE.match(date_str):
            skipped.append({"ligne": i, "raison": "Date invalide (format attendu : AAAA-MM-JJ)."})
            continue
        if entry.get("heure_arrivee") and heure_arrivee is None:
            skipped.append({"ligne": i, "raison": "Heure d'arrivée invalide (format attendu : HH:MM)."})
            continue
        if entry.get("heure_depart") and heure_depart is None:
            skipped.append({"ligne": i, "raison": "Heure de départ invalide (format attendu : HH:MM)."})
            continue
        try:
            conn.execute(
                """
                INSERT INTO pointages (nom, prenom, date, heure_arrivee, heure_depart, motif, source)
                VALUES (?, ?, ?, ?, ?, ?, 'manuel')""",(nom, prenom, date_str, heure_arrivee, heure_depart, motif),)
            inserted.append({"ligne": i, "nom": nom, "prenom": prenom, "date": date_str})
        except sqlite3.IntegrityError:
            skipped.append({"ligne": i, "raison": "Un pointage existe déjà pour ce nom à cette date."})

    conn.commit()
    conn.close()
    return jsonify({"inserted": inserted, "skipped": skipped})

@app.route("/api/export")
def export_csv():
    if not is_admin():
        return jsonify({"error": "Non autorisé."}), 401
    date_filter = request.args.get("date")
    rows = fetch_pointages(date_filter)
    output = io.StringIO()
    output.write("\ufeff") 
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Nom", "Prenom", "Date", "Heure arrivee", "Heure depart", "Motif", "Source"])
    for r in rows:
        writer.writerow(
            [r["nom"], r["prenom"], r["date"], r["heure_arrivee"] or "", r["heure_depart"] or "", r["motif"] or "", r["source"]])

    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    filename = f"pointages_{date_filter or 'tous'}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)
init_db()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

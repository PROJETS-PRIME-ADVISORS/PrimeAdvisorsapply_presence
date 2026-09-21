import pytest


def pointer(client, nom, prenom):
    return client.post("/api/pointage", json={"nom": nom, "prenom": prenom})


def test_arrivee_puis_depart(client, horloge):
    horloge.regler(8, 5)
    arrivee = pointer(client, "Kouadio", "Jean David").get_json()
    assert (arrivee["type"], arrivee["heure"]) == ("arrivee", "08:05:00")

    horloge.regler(17, 30)
    assert pointer(client, "Kouadio", "Jean David").get_json()["type"] == "depart"

    horloge.regler(18, 0)
    complet = pointer(client, "Kouadio", "Jean David").get_json()
    assert complet["type"] == "deja_complet"
    assert (complet["heure_arrivee"], complet["heure_depart"]) == ("08:05:00", "17:30:00")


def test_un_double_scan_ne_cloture_pas_la_journee(admin, horloge):
    horloge.regler(8, 0)
    pointer(admin, "Kouadio", "Jean David")

    horloge.regler(8, 1)
    second = pointer(admin, "Kouadio", "Jean David").get_json()
    assert (second["type"], second["depart_possible"]) == ("deja_arrive", "08:30")
    assert admin.get("/api/pointages").get_json()[0]["heure_depart"] is None

    horloge.regler(8, 30)
    assert pointer(admin, "Kouadio", "Jean David").get_json()["type"] == "depart"


def test_rapprochement_insensible_casse_accents_espaces(client, horloge):
    horloge.regler(8, 0)
    arrivee = pointer(client, "  éclésiaste ", "aka   andré").get_json()
    assert (arrivee["nom"], arrivee["prenom"]) == ("ÉCLÉSIASTE", "Aka André")

    horloge.regler(17, 0)
    depart = pointer(client, "ECLESIASTE", "AKA ANDRE").get_json()
    assert depart["type"] == "depart"
    assert (depart["nom"], depart["prenom"]) == ("ÉCLÉSIASTE", "Aka André")


def test_apostrophe_typographique_et_tiret(client, horloge):
    donnees = pointer(client, "n’guessan", "marie-claire").get_json()
    assert (donnees["nom"], donnees["prenom"]) == ("N'GUESSAN", "Marie-Claire")


@pytest.mark.parametrize("nom, prenom", [
    ("", "Jean"),
    ('=HYPERLINK("http://exemple")', "Jean"),
    ("Kouadio", "J" * 81),
    ("Kouadio2", "Jean"),
])
def test_identite_invalide_refusee(client, nom, prenom):
    reponse = pointer(client, nom, prenom)
    assert reponse.status_code == 400
    assert reponse.get_json()["error"]


@pytest.mark.parametrize("methode, url", [
    ("get", "/api/pointages"),
    ("get", "/api/export"),
    ("post", "/api/pointages/import"),
])
def test_routes_admin_protegees(client, methode, url):
    assert getattr(client, methode)(url).status_code == 401


def test_connexion_bloquee_apres_trop_d_echecs(client, module):
    for _ in range(module.MAX_ECHECS_CONNEXION):
        assert client.post("/admin/login", json={"password": "faux"}).status_code == 401
    assert client.post("/admin/login", json={"password": "mot-de-passe-test"}).status_code == 429


def test_deconnexion(admin):
    admin.post("/admin/logout")
    assert admin.get("/api/pointages").status_code == 401


def test_import_valide_et_rejette_les_lignes_incorrectes(admin, horloge):
    entries = [
        {"nom": "Kouadio", "prenom": "Jean David", "date": "2026-09-08",
         "heure_arrivee": "08:00", "heure_depart": "17:00", "motif": "Registre papier"},
        {"nom": "KOUADIO", "prenom": "jean-david", "date": "2026-09-08", "heure_arrivee": "08:10"},
        {"nom": "Aka", "prenom": "André", "date": "2026-09-30", "heure_arrivee": "08:00"},
        {"nom": "Aka", "prenom": "André", "date": "2026-02-30", "heure_arrivee": "08:00"},
        {"nom": "Aka", "prenom": "André", "date": "2026-09-09", "heure_arrivee": "25:00"},
        {"nom": "Aka", "prenom": "André", "date": "2026-09-09", "heure_arrivee": "17:00", "heure_depart": "08:00"},
        "pas une ligne",
    ]
    donnees = admin.post("/api/pointages/import", json={"entries": entries}).get_json()
    assert [ligne["ligne"] for ligne in donnees["inserted"]] == [1]
    assert [ligne["ligne"] for ligne in donnees["skipped"]] == [2, 3, 4, 5, 6, 7]

    pointages = admin.get("/api/pointages?date=2026-09-08").get_json()
    assert len(pointages) == 1
    assert (pointages[0]["source"], pointages[0]["heure_depart"]) == ("manuel", "17:00:00")


def test_export_csv_neutralise_les_formules(admin, horloge):
    admin.post("/api/pointages/import", json={"entries": [
        {"nom": "Aka", "prenom": "André", "date": "2026-09-10", "heure_arrivee": "08:00", "motif": "=1+1"}]})
    reponse = admin.get("/api/export?date=2026-09-10")
    assert reponse.status_code == 200
    contenu = reponse.get_data().decode("utf-8-sig")
    assert "AKA;André;2026-09-10;08:00:00;;'=1+1;manuel" in contenu


def test_filtre_date_invalide(admin):
    reponse = admin.get("/api/pointages?date=2026-13-01")
    assert reponse.status_code == 400
    assert reponse.get_json()["error"].startswith("Date invalide")


@pytest.mark.parametrize("url", ["/", "/admin", "/static/style.css", "/static/app.js", "/static/admin.js", "/static/logo.jpg"])
def test_pages_et_fichiers_statiques(client, url):
    reponse = client.get(url)
    assert reponse.status_code == 200
    reponse.close()

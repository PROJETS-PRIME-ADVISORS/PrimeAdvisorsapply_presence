import os
from datetime import datetime

import pytest

# Lues à l'import de app.py, donc définies avant. Les valeurs vides empêchent
# load_dotenv() de reprendre une base de production depuis un fichier .env.
os.environ.update({
    "ADMIN_PASSWORD": "mot-de-passe-test",
    "SESSION_SECRET": "secret-de-test",
    "DATABASE_URL": "",
    "POSTGRES_URL": "",
    "VERCEL": "",
})

import app as application  # noqa: E402

# Pour lancer les mêmes tests sur Postgres. Les tables de cette base sont supprimées
# à chaque test : ne jamais y mettre l'adresse de la base de production.
URL_POSTGRES_TEST = os.environ.get("TEST_DATABASE_URL")


class Horloge:
    def __init__(self):
        self.moment = datetime(2026, 9, 15, 8, 0, tzinfo=application.TIMEZONE)

    def regler(self, heure, minute=0):
        self.moment = self.moment.replace(hour=heure, minute=minute)


@pytest.fixture
def module(tmp_path, monkeypatch):
    if URL_POSTGRES_TEST:
        import psycopg
        with psycopg.connect(URL_POSTGRES_TEST, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS pointages, tentatives_connexion")
        monkeypatch.setattr(application, "DATABASE_URL", URL_POSTGRES_TEST)
    else:
        monkeypatch.setattr(application, "SQLITE_PATH", str(tmp_path / "pointage-test.db"))
    monkeypatch.setattr(application, "_schema_pret", False)
    return application


@pytest.fixture
def client(module):
    return module.app.test_client()


@pytest.fixture
def admin(client):
    assert client.post("/admin/login", json={"password": "mot-de-passe-test"}).status_code == 200
    return client


@pytest.fixture
def horloge(module, monkeypatch):
    """Fixe l'heure du serveur : horloge.regler(17, 30)."""
    h = Horloge()
    monkeypatch.setattr(module, "maintenant", lambda: h.moment)
    return h

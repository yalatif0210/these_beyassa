import pytest

from app import create_app
from app.models import Admin, Chirurgien, Parametres, db


@pytest.fixture
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "SECRET_KEY": "test",
    })
    with app.app_context():
        a = Admin(identifiant="admin")
        a.definir_mot_de_passe("motdepasse")
        db.session.add_all([a, Chirurgien(nom="Dr Test"), Chirurgien(nom="Dr Inactif", actif=False)])
        db.session.commit()
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def jeton(app):
    with app.app_context():
        return Parametres.courants().jeton_acces


@pytest.fixture
def chir(app, jeton):
    """Client chirurgien : a scanné le QR code et choisi son nom."""
    c = app.test_client()
    c.get(f"/acces/{jeton}")
    with app.app_context():
        cid = Chirurgien.query.filter_by(nom="Dr Test").first().id
    c.post("/qui-etes-vous", data={"chirurgien_id": cid})
    return c


@pytest.fixture
def adm(app):
    c = app.test_client()
    c.post("/admin/connexion", data={"identifiant": "admin", "mot_de_passe": "motdepasse"})
    return c

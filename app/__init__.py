import os
import secrets
from datetime import timedelta

import click
from flask import Flask, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from . import referentiels
from .models import Admin, Parametres, db, empreinte

VALEUR_EXEMPLE = "a_remplacer"

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def _bool_env(nom, defaut=False):
    return os.environ.get(nom, str(defaut)).lower() in ("1", "true", "oui", "yes")


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    # Une valeur d'exemple de .env.example oubliée (ex. mot de passe admin « a_remplacer ») : on refuse de démarrer.
    oublis = [n for n in ("SECRET_KEY", "ADMIN_MOT_DE_PASSE", "POSTGRES_PASSWORD") if os.environ.get(n) == VALEUR_EXEMPLE]
    if oublis:
        raise RuntimeError(f"Valeur d'exemple « {VALEUR_EXEMPLE} » à remplacer dans .env : {', '.join(oublis)}")

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        secret = secrets.token_hex(32)
        app.logger.warning("SECRET_KEY absent : clé temporaire générée (les sessions ne survivront pas au redémarrage).")

    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "beyassa.db")
        ),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        BASE_URL=os.environ.get("BASE_URL", "").rstrip("/"),
        ADMIN_IDENTIFIANT=os.environ.get("ADMIN_IDENTIFIANT"),
        ADMIN_MOT_DE_PASSE=os.environ.get("ADMIN_MOT_DE_PASSE"),
        NOM_ETUDE=os.environ.get("NOM_ETUDE", "Étude hydrocèle de l'enfant"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_bool_env("COOKIE_SECURISE", False),
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
        WTF_CSRF_TIME_LIMIT=None,
        RATELIMIT_STORAGE_URI=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        RATELIMIT_ENABLED=True,
    )
    if config:
        app.config.update(config)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from .admin import bp as admin_bp
    from .chirurgien import bp as chirurgien_bp

    app.register_blueprint(chirurgien_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    with app.app_context():
        db.create_all()
        Parametres.courants()
        _creer_admin_depuis_env(app)
        # Avec gunicorn --preload, ce code tourne dans le processus maître : on ferme ses connexions
        # pour que chaque worker ouvre les siennes au lieu de partager le même socket PostgreSQL.
        # (Pas pour une base SQLite en mémoire, les tests : la fermer l'effacerait.)
        if db.engine.url.database not in (None, "", ":memory:"):
            db.engine.dispose()

    @app.context_processor
    def injecter():
        return {"R": referentiels, "libelle": referentiels.libelle, "nom_etude": app.config["NOM_ETUDE"]}

    app.add_template_filter(empreinte, "empreinte")

    @app.template_filter("date_fr")
    def date_fr(d):
        return d.strftime("%d/%m/%Y") if d else ""

    @app.template_filter("nombre")
    def nombre(v):
        if v is None:
            return ""
        return f"{v:g}".replace(".", ",") if isinstance(v, float) else str(v)

    @app.after_request
    def entetes(resp):
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.errorhandler(404)
    def introuvable(_e):
        return render_template("message.html", titre="Page introuvable",
                               texte="Cette page n'existe pas."), 404

    @app.errorhandler(429)
    def trop(_e):
        return render_template("message.html", titre="Trop de requêtes",
                               texte="Patientez une minute avant de réessayer."), 429

    @app.errorhandler(CSRFError)
    def csrf_expire(_e):
        return render_template("message.html", titre="Formulaire expiré",
                               texte="Revenez en arrière, rechargez la page puis envoyez à nouveau le formulaire."), 400

    @app.cli.command("creer-admin")
    @click.option("--identifiant", prompt=True)
    @click.option("--mot-de-passe", prompt=True, hide_input=True, confirmation_prompt=True)
    def creer_admin(identifiant, mot_de_passe):
        """Crée le compte administrateur ou change son mot de passe."""
        a = Admin.query.filter_by(identifiant=identifiant).first() or Admin(identifiant=identifiant)
        a.definir_mot_de_passe(mot_de_passe)
        db.session.add(a)
        db.session.commit()
        click.echo(f"Compte administrateur « {identifiant} » enregistré.")

    @app.cli.command("lien-acces")
    def lien_acces():
        """Affiche le lien d'accès des chirurgiens (celui du QR code)."""
        p = Parametres.courants()
        base = app.config["BASE_URL"] or "http://localhost:8000"
        click.echo(f"{base}/acces/{p.jeton_acces}")

    return app


def _creer_admin_depuis_env(app):
    ident, mdp = app.config["ADMIN_IDENTIFIANT"], app.config["ADMIN_MOT_DE_PASSE"]
    if ident and mdp and Admin.query.count() == 0:
        a = Admin(identifiant=ident)
        a.definir_mot_de_passe(mdp)
        db.session.add(a)
        db.session.commit()
        app.logger.info("Compte administrateur initial créé.")

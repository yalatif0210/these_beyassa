"""Espace administrateur : tableau de bord, données complètes, corrections, paramètres, export."""
import io
from datetime import date, timedelta
from functools import wraps

import qrcode
import qrcode.image.svg
from flask import (Blueprint, Response, current_app, flash, redirect, render_template, request, session,
                   url_for, abort)
from markupsafe import Markup

from . import limiter
from .export import colonnes, csv_dictionnaire, csv_donnees
from .models import Admin, Chirurgien, Intervention, Parametres, Patient, Visite, db, nouveau_jeton
from .planning import ecart_jours, etats_patient, hors_fenetre
from .referentiels import CODES_ECHEANCES, COEFFICIENTS_VOLUME, LIBELLES_ECHEANCE
from .saisie import Lecteur, lire_intervention, lire_patient, lire_visite, valeurs_formulaire

bp = Blueprint("admin", __name__)


def admin_courant():
    aid = session.get("admin_id")
    return db.session.get(Admin, aid) if aid else None


def connexion_requise(vue):
    @wraps(vue)
    def enveloppe(*a, **k):
        if admin_courant() is None:
            return redirect(url_for("admin.connexion", suite=request.path))
        return vue(*a, **k)
    return enveloppe


@bp.app_context_processor
def contexte():
    return {"admin_connecte": admin_courant() if session.get("admin_id") else None}


# -------------------------------------------------------------- connexion

@bp.route("/connexion", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def connexion():
    if request.method == "POST":
        a = Admin.query.filter_by(identifiant=(request.form.get("identifiant") or "").strip()).first()
        if a and a.verifier(request.form.get("mot_de_passe") or ""):
            session.clear()
            session.permanent = True
            session["admin_id"] = a.id
            suite = request.args.get("suite") or ""
            if not suite.startswith("/admin"):
                suite = url_for("admin.tableau_de_bord")
            return redirect(suite)
        flash("Identifiant ou mot de passe incorrect.", "erreur")
    return render_template("admin/connexion.html")


@bp.route("/deconnexion", methods=["POST"])
def deconnexion():
    session.pop("admin_id", None)
    return redirect(url_for("admin.connexion"))


@bp.route("/mot-de-passe", methods=["GET", "POST"])
@connexion_requise
def mot_de_passe():
    if request.method == "POST":
        a = admin_courant()
        ancien, nouveau, conf = (request.form.get(k) or "" for k in ("ancien", "nouveau", "confirmation"))
        if not a.verifier(ancien):
            flash("Mot de passe actuel incorrect.", "erreur")
        elif len(nouveau) < 8:
            flash("Le nouveau mot de passe doit faire au moins 8 caractères.", "erreur")
        elif nouveau != conf:
            flash("La confirmation ne correspond pas.", "erreur")
        else:
            a.definir_mot_de_passe(nouveau)
            db.session.commit()
            flash("Mot de passe modifié.", "succes")
            return redirect(url_for("admin.tableau_de_bord"))
    return render_template("admin/mot_de_passe.html")


# --------------------------------------------------------- tableau de bord

@bp.route("/")
@connexion_requise
def tableau_de_bord():
    p = Parametres.courants()
    aujourdhui = date.today()
    patients = Patient.query.order_by(Patient.numero).all()
    a_faire, en_retard, a_venir, apres_fermeture = [], [], [], []
    realisees = non_realisees = attendues = 0
    for pt in patients:
        for e in etats_patient(pt, p, aujourdhui):
            if e.statut == "realisee":
                realisees += 1
            elif e.statut == "non_realisee":
                non_realisees += 1
            if e.date_prevue and e.date_prevue - timedelta(days=p.marge_jours) <= aujourdhui:
                attendues += 1
            if e.statut == "a_faire":
                a_faire.append(e)
            elif e.statut == "en_retard":
                en_retard.append(e)
            elif e.statut == "a_venir" and e.debut_fenetre <= aujourdhui + timedelta(days=14):
                a_venir.append(e)
            if e.apres_fermeture and e.statut in ("a_venir", "a_faire"):
                apres_fermeture.append(e)
    tri = lambda e: e.date_prevue
    stats = {
        "patients": len(patients),
        "objectif": p.objectif_patients,
        "interventions": sum(1 for pt in patients if pt.intervention),
        "scrotale": sum(1 for pt in patients if pt.intervention and pt.intervention.voie_abord == "scrotale"),
        "inguinale": sum(1 for pt in patients if pt.intervention and pt.intervention.voie_abord == "inguinale"),
        "realisees": realisees,
        "non_realisees": non_realisees,
        "attendues": attendues,
    }
    return render_template(
        "admin/tableau_de_bord.html", stats=stats, parametres=p,
        a_faire=sorted(a_faire, key=tri), en_retard=sorted(en_retard, key=tri),
        a_venir=sorted(a_venir, key=tri), apres_fermeture=sorted(apres_fermeture, key=tri),
    )


# ---------------------------------------------------------------- patients

@bp.route("/patients")
@connexion_requise
def patients():
    p = Parametres.courants()
    liste = [(pt, etats_patient(pt, p)) for pt in Patient.query.order_by(Patient.numero).all()]
    return render_template("admin/patients.html", liste=liste)


def _patient(numero):
    return Patient.query.filter_by(numero=numero).first_or_404()


@bp.route("/patient/<numero>")
@connexion_requise
def patient(numero):
    pt = _patient(numero)
    p = Parametres.courants()
    return render_template("admin/patient.html", patient=pt, etats=etats_patient(pt, p), coef=p.coefficient_volume,
                           ecart_jours=ecart_jours)


@bp.route("/patient/<numero>/modifier", methods=["GET", "POST"])
@connexion_requise
def modifier_patient(numero):
    pt = _patient(numero)
    valeurs, erreurs = valeurs_formulaire(pt), {}
    if request.method == "POST":
        valeurs = request.form.to_dict()
        erreurs = lire_patient(pt, request.form)
        if not erreurs:
            db.session.commit()
            flash("Inclusion modifiée.", "succes")
            return redirect(url_for("admin.patient", numero=numero))
        db.session.rollback()
    return render_template("formulaire.html", espace="admin", partiel="forms/_inclusion.html", patient=pt,
                           titre=f"Inclusion : {pt.numero}", valeurs=valeurs, erreurs=erreurs,
                           retour=url_for("admin.patient", numero=numero))


@bp.route("/patient/<numero>/intervention", methods=["GET", "POST"])
@connexion_requise
def intervention(numero):
    pt = _patient(numero)
    interv = pt.intervention
    valeurs = valeurs_formulaire(interv) or {"date_intervention": date.today().isoformat()}
    erreurs = {}
    if request.method == "POST":
        valeurs = request.form.to_dict()
        cible = interv or Intervention()
        erreurs = lire_intervention(cible, request.form, pt)
        if not erreurs:
            if interv is None:
                cible.patient = pt
                db.session.add(cible)
            db.session.commit()
            flash("Intervention enregistrée.", "succes")
            return redirect(url_for("admin.patient", numero=numero))
        db.session.rollback()
    return render_template("formulaire.html", espace="admin", partiel="forms/_intervention.html", patient=pt,
                           titre=f"Intervention : {pt.numero}", valeurs=valeurs, erreurs=erreurs,
                           retour=url_for("admin.patient", numero=numero))


@bp.route("/patient/<numero>/visite/<echeance>", methods=["GET", "POST"])
@connexion_requise
def visite(numero, echeance):
    pt = _patient(numero)
    if echeance not in CODES_ECHEANCES:
        abort(404)
    if pt.intervention is None:
        flash("Saisissez d'abord l'intervention.", "info")
        return redirect(url_for("admin.patient", numero=numero))
    v = pt.visite(echeance)
    valeurs = valeurs_formulaire(v) if v and v.statut == "realisee" else {"date_visite": date.today().isoformat()}
    erreurs = {}
    if request.method == "POST":
        valeurs = request.form.to_dict()
        if request.form.get("action") == "non_realisee":
            if v is None:
                v = Visite(patient=pt, echeance=echeance)
                db.session.add(v)
            v.statut = "non_realisee"
            db.session.commit()
            flash(f"Visite {echeance} marquée comme non réalisée.", "succes")
            return redirect(url_for("admin.patient", numero=numero))
        cible = v or Visite(echeance=echeance)
        erreurs = lire_visite(cible, request.form, echeance, pt)
        if not erreurs:
            if v is None:
                cible.patient = pt
                db.session.add(cible)
            db.session.commit()
            msg = f"Visite {echeance} enregistrée."
            if hors_fenetre(pt, echeance, cible.date_visite, Parametres.courants()):
                msg += " La date est en dehors de la marge prévue."
            flash(msg, "succes")
            return redirect(url_for("admin.patient", numero=numero))
        db.session.rollback()
    return render_template("formulaire.html", espace="admin", partiel="forms/_visite.html", patient=pt,
                           echeance=echeance, titre=f"Visite {LIBELLES_ECHEANCE[echeance]} : {pt.numero}",
                           valeurs=valeurs, erreurs=erreurs, retour=url_for("admin.patient", numero=numero),
                           bouton_non_realisee=True)


@bp.route("/patient/<numero>/visite/<echeance>/effacer", methods=["POST"])
@connexion_requise
def effacer_visite(numero, echeance):
    pt = _patient(numero)
    v = pt.visite(echeance)
    if v:
        db.session.delete(v)
        db.session.commit()
        flash(f"Visite {echeance} effacée : elle peut être saisie à nouveau.", "succes")
    return redirect(url_for("admin.patient", numero=numero))


@bp.route("/patient/<numero>/supprimer", methods=["POST"])
@connexion_requise
def supprimer_patient(numero):
    pt = _patient(numero)
    if request.form.get("confirmation") != pt.numero:
        flash(f"Pour supprimer, tapez exactement {pt.numero}.", "erreur")
        return redirect(url_for("admin.patient", numero=numero))
    db.session.delete(pt)
    db.session.commit()
    flash(f"Patient {numero} supprimé.", "succes")
    return redirect(url_for("admin.patients"))


# -------------------------------------------------------------- chirurgiens

@bp.route("/chirurgiens", methods=["GET", "POST"])
@connexion_requise
def chirurgiens():
    if request.method == "POST":
        nom = " ".join((request.form.get("nom") or "").split())
        if not nom:
            flash("Indiquez un nom.", "erreur")
        elif Chirurgien.query.filter(db.func.lower(Chirurgien.nom) == nom.lower()).first():
            flash("Ce nom existe déjà.", "erreur")
        else:
            db.session.add(Chirurgien(nom=nom))
            db.session.commit()
            flash(f"{nom} ajouté.", "succes")
        return redirect(url_for("admin.chirurgiens"))
    return render_template("admin/chirurgiens.html", chirurgiens=Chirurgien.query.order_by(Chirurgien.nom).all())


@bp.route("/chirurgiens/<int:cid>/basculer", methods=["POST"])
@connexion_requise
def basculer_chirurgien(cid):
    c = db.session.get(Chirurgien, cid) or abort(404)
    c.actif = not c.actif
    db.session.commit()
    flash(f"{c.nom} {'réactivé' if c.actif else 'désactivé'}.", "succes")
    return redirect(url_for("admin.chirurgiens"))


# --------------------------------------------------------------- paramètres

def lien_acces(p):
    base = current_app.config["BASE_URL"] or request.url_root.rstrip("/")
    return f"{base}{url_for('chirurgien.acces', jeton=p.jeton_acces)}"


def qr_svg(texte):
    img = qrcode.make(texte, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


@bp.route("/parametres", methods=["GET", "POST"])
@connexion_requise
def parametres():
    p = Parametres.courants()
    erreurs = {}
    if request.method == "POST":
        L = Lecteur(request.form)
        marge = L.entier("marge_jours", 0, 30)
        objectif = L.entier("objectif_patients", 1, 10000)
        coef = L.choix("coefficient_volume", COEFFICIENTS_VOLUME)
        ouverture = _date_libre(L, "date_ouverture")
        fermeture = _date_libre(L, "date_fermeture")
        if ouverture and fermeture and fermeture < ouverture:
            L.erreurs["date_fermeture"] = "La fermeture doit suivre l'ouverture."
        erreurs = L.erreurs
        if not erreurs:
            p.marge_jours, p.objectif_patients, p.coefficient_volume = marge, objectif, float(coef)
            p.date_ouverture, p.date_fermeture = ouverture, fermeture
            db.session.commit()
            flash("Paramètres enregistrés.", "succes")
            return redirect(url_for("admin.parametres"))
    return render_template("admin/parametres.html", p=p, erreurs=erreurs, lien=lien_acces(p),
                           qr=Markup(qr_svg(lien_acces(p))))


def _date_libre(L, nom):
    v = (L.form.get(nom) or "").strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        L.erreurs[nom] = "Date invalide."
        return None


@bp.route("/parametres/nouveau-qr", methods=["POST"])
@connexion_requise
def nouveau_qr():
    p = Parametres.courants()
    p.jeton_acces = nouveau_jeton()
    db.session.commit()
    flash("Nouveau QR code généré. L'ancien ne fonctionne plus : imprimez et affichez le nouveau.", "succes")
    return redirect(url_for("admin.parametres"))


@bp.route("/affiche")
@connexion_requise
def affiche():
    p = Parametres.courants()
    return render_template("admin/affiche.html", qr=Markup(qr_svg(lien_acces(p))))


# ------------------------------------------------------------------- export

@bp.route("/export")
@connexion_requise
def export():
    p = Parametres.courants()
    return render_template("admin/export.html", nb=Patient.query.count(), nb_colonnes=len(colonnes(p.coefficient_volume)))


@bp.route("/export/donnees.csv")
@connexion_requise
def export_donnees():
    p = Parametres.courants()
    style = "standard" if request.args.get("style") == "standard" else "excel"
    contenu = csv_donnees(Patient.query.order_by(Patient.numero).all(), p.coefficient_volume, style)
    nom = f"beyassa_donnees_{style}_{date.today():%Y%m%d}.csv"
    return Response(contenu, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={nom}"})


@bp.route("/export/dictionnaire.csv")
@connexion_requise
def export_dictionnaire():
    p = Parametres.courants()
    return Response(csv_dictionnaire(p.coefficient_volume), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=beyassa_dictionnaire_variables.csv"})

"""Espace chirurgien : accès par QR code, sans compte."""
import hmac
import re
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from . import limiter
from .models import Chirurgien, Intervention, Parametres, Patient, Visite, db
from .planning import etats_patient, hors_fenetre
from .referentiels import CODES_ECHEANCES, LIBELLES_ECHEANCE
from .saisie import lire_intervention, lire_patient, lire_visite, valeurs_formulaire

bp = Blueprint("chirurgien", __name__)

ROUTES_LIBRES = {"chirurgien.acces", "chirurgien.acces_requis", "chirurgien.choisir_nom"}


def _acces_valide():
    jeton = session.get("acces")
    return bool(jeton) and hmac.compare_digest(jeton, Parametres.courants().jeton_acces)


def chirurgien_courant():
    cid = session.get("chirurgien_id")
    if not cid:
        return None
    c = db.session.get(Chirurgien, cid)
    return c if c and c.actif else None


@bp.before_request
def verifier_acces():
    if request.endpoint in ROUTES_LIBRES or request.endpoint is None:
        return None
    if not _acces_valide():
        return redirect(url_for("chirurgien.acces_requis"))
    if chirurgien_courant() is None:
        return redirect(url_for("chirurgien.choisir_nom", suite=request.full_path))
    return None


@bp.app_context_processor
def contexte():
    return {"chirurgien_connecte": chirurgien_courant() if session.get("chirurgien_id") else None}


# ------------------------------------------------------------------ accès

@bp.route("/acces/<jeton>")
@limiter.limit("20 per minute")
def acces(jeton):
    if not hmac.compare_digest(jeton, Parametres.courants().jeton_acces):
        return render_template("chirurgien/acces_requis.html", invalide=True), 403
    session.permanent = True
    session["acces"] = jeton
    # Redirection : le jeton ne reste pas dans la barre d'adresse.
    return redirect(url_for("chirurgien.accueil"))


@bp.route("/bienvenue")
def acces_requis():
    if _acces_valide():
        return redirect(url_for("chirurgien.accueil"))
    return render_template("chirurgien/acces_requis.html", invalide=False)


@bp.route("/qui-etes-vous", methods=["GET", "POST"])
def choisir_nom():
    if not _acces_valide():
        return redirect(url_for("chirurgien.acces_requis"))
    suite = request.values.get("suite") or url_for("chirurgien.accueil")
    if not suite.startswith("/") or suite.startswith("//"):
        suite = url_for("chirurgien.accueil")
    chirurgiens = Chirurgien.query.filter_by(actif=True).order_by(Chirurgien.nom).all()
    if request.method == "POST":
        c = db.session.get(Chirurgien, request.form.get("chirurgien_id", type=int) or 0)
        if c and c.actif:
            session["chirurgien_id"] = c.id
            return redirect(suite)
        flash("Choisissez votre nom dans la liste.", "erreur")
    return render_template("chirurgien/choix_nom.html", chirurgiens=chirurgiens, suite=suite)


@bp.route("/changer-de-nom")
def changer_nom():
    session.pop("chirurgien_id", None)
    return redirect(url_for("chirurgien.choisir_nom"))


# ---------------------------------------------------------------- accueil

@bp.route("/")
def accueil():
    return render_template("chirurgien/accueil.html", resultats=None, q="")


@bp.route("/recherche")
@limiter.limit("30 per minute")
def recherche():
    q = (request.args.get("q") or "").strip().upper().replace(".", "").replace(" ", "")
    resultats = []
    if q:
        conditions = [Patient.initiales == q]
        m = re.fullmatch(r"(?:HYD-?)?(\d{1,4})", q)
        if m:
            conditions.append(Patient.numero == f"HYD-{int(m.group(1)):03d}")
        resultats = Patient.query.filter(or_(*conditions)).order_by(Patient.numero).limit(20).all()
    p = Parametres.courants()
    lignes = [(pt, etats_patient(pt, p)) for pt in resultats]
    return render_template("chirurgien/accueil.html", resultats=lignes, q=request.args.get("q", ""))


# --------------------------------------------------------------- patients

def _patient_ou_404(numero):
    return Patient.query.filter_by(numero=numero).first_or_404()


def _prochain_numero():
    dernier = db.session.query(func.max(Patient.id)).scalar() or 0
    n = dernier + 1
    while Patient.query.filter_by(numero=f"HYD-{n:03d}").first():
        n += 1
    return f"HYD-{n:03d}"


def doublons_possibles(initiales, age):
    if not initiales or age is None:
        return []
    return (
        Patient.query.filter(Patient.initiales == initiales, Patient.age_ans.between(age - 1, age + 1))
        .order_by(Patient.numero)
        .all()
    )


@bp.route("/nouveau", methods=["GET", "POST"])
def nouveau_patient():
    valeurs = {"date_consultation": date.today().isoformat()}
    erreurs, doublons = {}, []
    if request.method == "POST":
        valeurs = request.form.to_dict()
        patient = Patient()
        erreurs = lire_patient(patient, request.form)
        if not erreurs:
            doublons = doublons_possibles(patient.initiales, patient.age_ans)
            if doublons and not request.form.get("confirmer_nouveau"):
                return render_template("chirurgien/nouveau.html", valeurs=valeurs, erreurs={}, doublons=doublons)
            patient.chirurgien_id = chirurgien_courant().id
            for _ in range(3):
                patient.numero = _prochain_numero()
                db.session.add(patient)
                try:
                    db.session.commit()
                    break
                except IntegrityError:
                    db.session.rollback()
            else:
                abort(500)
            return render_template("chirurgien/patient_cree.html", patient=patient)
    return render_template("chirurgien/nouveau.html", valeurs=valeurs, erreurs=erreurs, doublons=doublons)


@bp.route("/patient/<numero>")
def patient(numero):
    pt = _patient_ou_404(numero)
    return render_template("chirurgien/patient.html", patient=pt, etats=etats_patient(pt, Parametres.courants()))


@bp.route("/patient/<numero>/intervention", methods=["GET", "POST"])
def intervention(numero):
    pt = _patient_ou_404(numero)
    if pt.intervention is not None:
        flash("L'intervention de ce patient est déjà saisie. Pour une correction, contactez l'administratrice.", "info")
        return redirect(url_for("chirurgien.patient", numero=numero))
    valeurs, erreurs = {"date_intervention": date.today().isoformat()}, {}
    if request.method == "POST":
        valeurs = request.form.to_dict()
        interv = Intervention()
        erreurs = lire_intervention(interv, request.form, pt)
        if not erreurs:
            interv.chirurgien_id = chirurgien_courant().id
            interv.patient = pt
            db.session.add(interv)
            db.session.commit()
            flash("Intervention enregistrée.", "succes")
            return redirect(url_for("chirurgien.patient", numero=numero))
    return render_template(
        "formulaire.html", espace="chirurgien", partiel="forms/_intervention.html", patient=pt,
        titre=f"Intervention : {pt.numero}", valeurs=valeurs, erreurs=erreurs,
        retour=url_for("chirurgien.patient", numero=numero),
    )


@bp.route("/patient/<numero>/visite/<echeance>", methods=["GET", "POST"])
def visite(numero, echeance):
    pt = _patient_ou_404(numero)
    if echeance not in CODES_ECHEANCES:
        abort(404)
    if pt.intervention is None:
        flash("Saisissez d'abord l'intervention.", "info")
        return redirect(url_for("chirurgien.patient", numero=numero))
    if pt.visite(echeance) is not None:
        flash(f"La visite {echeance} est déjà enregistrée. Pour une correction, contactez l'administratrice.", "info")
        return redirect(url_for("chirurgien.patient", numero=numero))

    p = Parametres.courants()
    valeurs, erreurs = {"date_visite": date.today().isoformat()}, {}
    if request.method == "POST":
        valeurs = request.form.to_dict()
        if request.form.get("action") == "non_realisee":
            v = Visite(patient=pt, echeance=echeance, statut="non_realisee", chirurgien_id=chirurgien_courant().id)
            db.session.add(v)
            db.session.commit()
            flash(f"Visite {echeance} marquée comme non réalisée.", "succes")
            return redirect(url_for("chirurgien.patient", numero=numero))
        v = Visite(echeance=echeance)
        erreurs = lire_visite(v, request.form, echeance, pt)
        if not erreurs:
            v.chirurgien_id = chirurgien_courant().id
            v.patient = pt
            db.session.add(v)
            db.session.commit()
            msg = f"Visite {echeance} enregistrée."
            if hors_fenetre(pt, echeance, v.date_visite, p):
                msg += " Attention : la date est en dehors de la marge prévue."
            flash(msg, "succes")
            return redirect(url_for("chirurgien.patient", numero=numero))
    return render_template(
        "formulaire.html", espace="chirurgien", partiel="forms/_visite.html", patient=pt, echeance=echeance,
        titre=f"Visite {LIBELLES_ECHEANCE[echeance]} : {pt.numero}", valeurs=valeurs, erreurs=erreurs,
        retour=url_for("chirurgien.patient", numero=numero), bouton_non_realisee=True,
    )


__all__ = ["bp", "doublons_possibles", "valeurs_formulaire"]

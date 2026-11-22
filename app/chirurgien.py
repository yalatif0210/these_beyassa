"""Espace chirurgien : accès par QR code, sans compte.

Idempotence : chaque formulaire porte un jeton d'envoi (`_page`), généré à l'affichage.
Une saisie réussie enregistre ce jeton (table `envois`) dans la même transaction.
Un envoi rejoué (double appui, rechargement, réponse perdue pendant une coupure réseau)
est reconnu et renvoie vers le résultat déjà enregistré, sans rien créer en double.
"""
import json
import re
import secrets
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_limiter.util import get_remote_address
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from . import limiter
from .models import (Brouillon, Chirurgien, Envoi, Intervention, Parametres, Patient, Visite, db, jetons_egaux,
                     maintenant)
from .planning import etats_patient, hors_fenetre
from .referentiels import CODES_ECHEANCES, LIBELLES_ECHEANCE
from .saisie import lire_intervention, lire_patient, lire_visite, valeurs_formulaire

bp = Blueprint("chirurgien", __name__)

ROUTES_LIBRES = {"chirurgien.acces", "chirurgien.acces_requis", "chirurgien.choisir_nom"}

# Clés de brouillon acceptées : un formulaire précis, jamais un texte libre.
MOTIF_CLE = re.compile(r"^(nouveau|intervention:HYD-\d{3,4}|visite:HYD-\d{3,4}:(%s))$" % "|".join(CODES_ECHEANCES))
MOTIF_JETON = re.compile(r"^[0-9a-f]{16,32}$")
CHAMPS_TECHNIQUES = {"csrf_token", "_cle", "_page", "_seq", "action", "confirmer_nouveau"}
TAILLE_MAX_BROUILLON = 20_000
MESSAGE_VERROU = ("Votre nom est verrouillé sur ce téléphone depuis votre première saisie. "
                  "Pour le changer, contactez l'administratrice.")


def _acces_valide():
    jeton = session.get("acces")
    return jetons_egaux(jeton, Parametres.courants().jeton_acces)


def cle_limite():
    """Compteur de limite par téléphone.

    Ni l'IP (les téléphones du service sortent souvent par la même IP publique), ni le chirurgien
    (il peut saisir sur plusieurs téléphones à la fois) : un identifiant d'appareil tiré au scan du
    QR code et gardé dans la session signée.
    """
    appareil = session.get("appareil")
    if appareil:
        return f"appareil:{appareil}"
    cid = session.get("chirurgien_id")
    return f"chirurgien:{cid}" if cid else get_remote_address()


def _identifier_appareil():
    if "appareil" not in session:
        session["appareil"] = secrets.token_hex(8)


def chirurgien_courant():
    cid = session.get("chirurgien_id")
    if not cid:
        return None
    c = db.session.get(Chirurgien, cid)
    if not c or not c.actif:
        return None
    # L'administratrice a « libéré » les téléphones de ce chirurgien : il faut rechoisir le nom.
    if session.get("chirurgien_gen", 0) != c.generation_session:
        return None
    return c


def nom_verrouille():
    """Le nom ne peut plus être changé sur ce téléphone après une première saisie enregistrée."""
    return bool(session.get("nom_verrouille")) and chirurgien_courant() is not None


def _verrouiller_nom():
    session["nom_verrouille"] = True


@bp.before_request
def verifier_acces():
    if request.endpoint in ROUTES_LIBRES or request.endpoint is None:
        return None
    if not _acces_valide():
        return redirect(url_for("chirurgien.acces_requis"))
    _identifier_appareil()  # sessions ouvertes avant l'existence de cet identifiant
    if chirurgien_courant() is None:
        return redirect(url_for("chirurgien.choisir_nom", suite=request.full_path))
    return None


@bp.app_context_processor
def contexte():
    return {
        "chirurgien_connecte": chirurgien_courant() if session.get("chirurgien_id") else None,
        "nom_verrouille": nom_verrouille() if session.get("chirurgien_id") else False,
    }


# ------------------------------------------------------------------ accès

@bp.route("/acces/<jeton>")
@limiter.limit("20 per minute")
def acces(jeton):
    if not jetons_egaux(jeton, Parametres.courants().jeton_acces):
        return render_template("chirurgien/acces_requis.html", invalide=True), 403
    session.permanent = True
    session["acces"] = jeton
    _identifier_appareil()
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
    if nom_verrouille():
        flash(MESSAGE_VERROU, "info")
        return redirect(url_for("chirurgien.accueil"))
    chirurgiens = Chirurgien.query.filter_by(actif=True).order_by(Chirurgien.nom).all()
    if request.method == "POST":
        c = db.session.get(Chirurgien, request.form.get("chirurgien_id", type=int) or 0)
        if c and c.actif:
            session["chirurgien_id"] = c.id
            session["chirurgien_gen"] = c.generation_session
            session["nom_verrouille"] = False
            return redirect(suite)
        flash("Choisissez votre nom dans la liste.", "erreur")
    return render_template("chirurgien/choix_nom.html", chirurgiens=chirurgiens, suite=suite)


@bp.route("/changer-de-nom")
def changer_nom():
    if nom_verrouille():
        flash(MESSAGE_VERROU, "info")
        return redirect(url_for("chirurgien.accueil"))
    session.pop("chirurgien_id", None)
    return redirect(url_for("chirurgien.choisir_nom"))


# ------------------------------------------------------- envois (idempotence)

def _jeton_envoi(form):
    jeton = (form.get("_page") or "").strip()
    return jeton if MOTIF_JETON.match(jeton) else None


def _envoi_deja_traite(form):
    """URL du résultat si ce formulaire a déjà été enregistré (envoi rejoué), sinon None."""
    jeton = _jeton_envoi(form)
    if not jeton:
        return None
    e = Envoi.query.filter_by(jeton=jeton).first()
    return e.resultat if e else None


def _noter_envoi(form, cle, resultat):
    """À appeler dans la transaction de la saisie : le jeton et la saisie sont validés ensemble."""
    jeton = _jeton_envoi(form)
    if jeton:
        db.session.add(Envoi(jeton=jeton, chirurgien_id=chirurgien_courant().id, cle=cle, resultat=resultat))


def _rejouer(url, message="Cette saisie était déjà enregistrée : rien n'a été créé en double."):
    _verrouiller_nom()
    flash(message, "succes")
    return redirect(url)


# --------------------------------------------------------------- brouillons

def _entier(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n < 10**15 else None


def _brouillon(cle):
    c = chirurgien_courant()
    return Brouillon.query.filter_by(chirurgien_id=c.id, cle=cle).first() if c else None


def _donnees_formulaire(form):
    return {k: v for k, v in form.items() if k not in CHAMPS_TECHNIQUES}


def _enregistrer_brouillon(cle, form, _essai=0):
    """Crée ou met à jour le brouillon, de façon idempotente et dans l'ordre.

    Ignorés : une sauvegarde d'une page déjà enregistrée (arrivée en retard), une sauvegarde
    plus ancienne que celle déjà stockée (`_seq`, horodatage de la modification côté téléphone),
    et le renvoi d'une sauvegarde déjà reçue (même `_seq`).
    """
    page = (form.get("_page") or "")[:32]
    seq = _entier(form.get("_seq"))
    donnees = json.dumps(_donnees_formulaire(form), ensure_ascii=False)
    if len(donnees) > TAILLE_MAX_BROUILLON:
        abort(413)
    b = _brouillon(cle)
    if b is None:
        b = Brouillon(chirurgien_id=chirurgien_courant().id, cle=cle, seq=0)
        db.session.add(b)
    else:
        if b.clos and b.page == page:
            return
        if seq is not None and seq <= (b.seq or 0):
            return
    b.page, b.donnees, b.clos = page, donnees, False
    b.seq = seq if seq is not None else (b.seq or 0) + 1
    b.maj_le = maintenant()
    try:
        db.session.commit()
    except IntegrityError:
        # Deux sauvegardes simultanées ont créé la même ligne : on recommence en mise à jour.
        db.session.rollback()
        if _essai == 0:
            _enregistrer_brouillon(cle, form, _essai=1)


def _clore_brouillon(cle, form):
    """Appelé dans la même transaction que l'enregistrement de la saisie."""
    b = _brouillon(cle)
    if b is None:
        b = Brouillon(chirurgien_id=chirurgien_courant().id, cle=cle, seq=0)
        db.session.add(b)
    b.page, b.donnees, b.clos = (form.get("_page") or "")[:32], "{}", True
    b.seq = max(b.seq or 0, _entier(form.get("_seq")) or 0)


def _contexte_brouillon(cle, valeurs):
    """Valeurs à afficher (brouillon restauré s'il existe) et variables pour le gabarit."""
    ctx = {"cle_brouillon": cle, "page_brouillon": secrets.token_hex(8), "brouillon_restaure": None,
           "brouillon_serveur": {"page": "", "seq": 0, "clos": False}}
    b = _brouillon(cle)
    if b is not None:
        ctx["brouillon_serveur"] = {"page": b.page, "seq": b.seq or 0, "clos": bool(b.clos)}
    if request.method == "GET" and b is not None and not b.clos:
        try:
            restaurees = json.loads(b.donnees)
        except ValueError:
            restaurees = {}
        if restaurees:
            valeurs = restaurees
            ctx["brouillon_restaure"] = max(0, int((maintenant() - b.maj_le).total_seconds() // 60))
    return valeurs, ctx


def _reprendre_page(ctx):
    """Après un envoi refusé (champs à corriger), la page garde son jeton d'envoi."""
    jeton = _jeton_envoi(request.form)
    if jeton:
        ctx["page_brouillon"] = jeton


@bp.route("/brouillon", methods=["POST"])
@limiter.limit("120 per minute", key_func=cle_limite)
def sauver_brouillon():
    cle = request.form.get("_cle", "")
    if not MOTIF_CLE.match(cle):
        abort(400)
    _enregistrer_brouillon(cle, request.form)
    return "", 204


@bp.route("/brouillon/effacer", methods=["POST"])
def effacer_brouillon():
    cle = request.form.get("_cle", "")
    if not MOTIF_CLE.match(cle):
        abort(400)
    b = _brouillon(cle)
    if b is not None:
        db.session.delete(b)
        db.session.commit()
    parties = cle.split(":")
    if parties[0] == "nouveau":
        return redirect(url_for("chirurgien.nouveau_patient"))
    if parties[0] == "intervention":
        return redirect(url_for("chirurgien.intervention", numero=parties[1]))
    return redirect(url_for("chirurgien.visite", numero=parties[1], echeance=parties[2]))


# ---------------------------------------------------------------- accueil

@bp.route("/")
def accueil():
    return render_template("chirurgien/accueil.html", resultats=None, q="")


@bp.route("/recherche")
@limiter.limit("30 per minute", key_func=cle_limite)
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
    # Le numéro suit le plus grand numéro existant (et non l'id : une séquence PostgreSQL laisse des trous).
    n = max((int(num[4:]) for (num,) in db.session.query(Patient.numero) if num[4:].isdigit()), default=0) + 1
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
    cle = "nouveau"
    if request.method == "POST":
        deja = _envoi_deja_traite(request.form)
        if deja:
            return _rejouer(deja, "Ce patient était déjà enregistré : aucun doublon n'a été créé.")
    valeurs, ctx = _contexte_brouillon(cle, {"date_consultation": date.today().isoformat()})
    erreurs, doublons = {}, []
    if request.method == "POST":
        valeurs = _donnees_formulaire(request.form)
        _reprendre_page(ctx)
        patient = Patient()
        erreurs = lire_patient(patient, request.form)
        if not erreurs:
            doublons = doublons_possibles(patient.initiales, patient.age_ans)
            if doublons and not request.form.get("confirmer_nouveau"):
                db.session.rollback()
                _enregistrer_brouillon(cle, request.form)
                return render_template("chirurgien/nouveau.html", valeurs=valeurs, erreurs={}, doublons=doublons, **ctx)
            patient.chirurgien_id = chirurgien_courant().id
            for _ in range(3):
                patient.numero = _prochain_numero()
                db.session.add(patient)
                _clore_brouillon(cle, request.form)
                _noter_envoi(request.form, cle, url_for("chirurgien.patient_cree", numero=patient.numero))
                try:
                    db.session.commit()
                    break
                except IntegrityError:
                    db.session.rollback()
                    # Envoi simultané du même formulaire : l'autre requête a déjà créé le patient.
                    deja = _envoi_deja_traite(request.form)
                    if deja:
                        return _rejouer(deja, "Ce patient était déjà enregistré : aucun doublon n'a été créé.")
                    patient = Patient()
                    lire_patient(patient, request.form)
                    patient.chirurgien_id = chirurgien_courant().id
            else:
                abort(500)
            _verrouiller_nom()
            # Redirection après envoi : recharger la page de confirmation ne renvoie pas le formulaire.
            return redirect(url_for("chirurgien.patient_cree", numero=patient.numero))
        db.session.rollback()
        _enregistrer_brouillon(cle, request.form)
    return render_template("chirurgien/nouveau.html", valeurs=valeurs, erreurs=erreurs, doublons=doublons, **ctx)


@bp.route("/patient/<numero>/enregistre")
def patient_cree(numero):
    return render_template("chirurgien/patient_cree.html", patient=_patient_ou_404(numero))


@bp.route("/patient/<numero>")
def patient(numero):
    pt = _patient_ou_404(numero)
    return render_template("chirurgien/patient.html", patient=pt, etats=etats_patient(pt, Parametres.courants()))


@bp.route("/patient/<numero>/intervention", methods=["GET", "POST"])
def intervention(numero):
    pt = _patient_ou_404(numero)
    retour = url_for("chirurgien.patient", numero=numero)
    if request.method == "POST":
        deja = _envoi_deja_traite(request.form)
        if deja:
            return _rejouer(deja, "L'intervention était déjà enregistrée : rien n'a été créé en double.")
    if pt.intervention is not None:
        flash("L'intervention de ce patient est déjà saisie. Pour une correction, contactez l'administratrice.", "info")
        return redirect(retour)
    cle = f"intervention:{pt.numero}"
    valeurs, ctx = _contexte_brouillon(cle, {"date_intervention": date.today().isoformat()})
    erreurs = {}
    if request.method == "POST":
        valeurs = _donnees_formulaire(request.form)
        _reprendre_page(ctx)
        interv = Intervention()
        erreurs = lire_intervention(interv, request.form, pt)
        if not erreurs:
            interv.chirurgien_id = chirurgien_courant().id
            interv.patient = pt
            db.session.add(interv)
            _clore_brouillon(cle, request.form)
            _noter_envoi(request.form, cle, retour)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                deja = _envoi_deja_traite(request.form)
                if deja:
                    return _rejouer(deja, "L'intervention était déjà enregistrée : rien n'a été créé en double.")
                flash("L'intervention de ce patient vient d'être saisie par ailleurs. "
                      "Pour une correction, contactez l'administratrice.", "info")
                return redirect(retour)
            _verrouiller_nom()
            flash("Intervention enregistrée.", "succes")
            return redirect(retour)
        db.session.rollback()
        _enregistrer_brouillon(cle, request.form)
    return render_template(
        "formulaire.html", espace="chirurgien", partiel="forms/_intervention.html", patient=pt,
        titre=f"Intervention : {pt.numero}", valeurs=valeurs, erreurs=erreurs, retour=retour, **ctx,
    )


@bp.route("/patient/<numero>/visite/<echeance>", methods=["GET", "POST"])
def visite(numero, echeance):
    pt = _patient_ou_404(numero)
    if echeance not in CODES_ECHEANCES:
        abort(404)
    retour = url_for("chirurgien.patient", numero=numero)
    if request.method == "POST":
        deja = _envoi_deja_traite(request.form)
        if deja:
            return _rejouer(deja, f"La visite {echeance} était déjà enregistrée : rien n'a été créé en double.")
    if pt.intervention is None:
        flash("Saisissez d'abord l'intervention.", "info")
        return redirect(retour)
    if pt.visite(echeance) is not None:
        flash(f"La visite {echeance} est déjà enregistrée. Pour une correction, contactez l'administratrice.", "info")
        return redirect(retour)

    p = Parametres.courants()
    cle = f"visite:{pt.numero}:{echeance}"
    valeurs, ctx = _contexte_brouillon(cle, {"date_visite": date.today().isoformat()})
    erreurs = {}
    if request.method == "POST":
        valeurs = _donnees_formulaire(request.form)
        _reprendre_page(ctx)
        non_realisee = request.form.get("action") == "non_realisee"
        if non_realisee:
            v = Visite(patient=pt, echeance=echeance, statut="non_realisee", chirurgien_id=chirurgien_courant().id)
            msg = f"Visite {echeance} marquée comme non réalisée."
        else:
            v = Visite(echeance=echeance)
            erreurs = lire_visite(v, request.form, echeance, pt)
            if not erreurs:
                v.chirurgien_id = chirurgien_courant().id
                v.patient = pt
                msg = f"Visite {echeance} enregistrée."
                if hors_fenetre(pt, echeance, v.date_visite, p):
                    msg += " Attention : la date est en dehors de la marge prévue."
        if not erreurs:
            db.session.add(v)
            _clore_brouillon(cle, request.form)
            _noter_envoi(request.form, cle, retour)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                deja = _envoi_deja_traite(request.form)
                if deja:
                    return _rejouer(deja, f"La visite {echeance} était déjà enregistrée : rien n'a été créé en double.")
                flash(f"La visite {echeance} vient d'être saisie par ailleurs. "
                      "Pour une correction, contactez l'administratrice.", "info")
                return redirect(retour)
            _verrouiller_nom()
            flash(msg, "succes")
            return redirect(retour)
        db.session.rollback()
        _enregistrer_brouillon(cle, request.form)
    return render_template(
        "formulaire.html", espace="chirurgien", partiel="forms/_visite.html", patient=pt, echeance=echeance,
        titre=f"Visite {LIBELLES_ECHEANCE[echeance]} : {pt.numero}", valeurs=valeurs, erreurs=erreurs,
        retour=retour, bouton_non_realisee=True, **ctx,
    )


__all__ = ["bp", "doublons_possibles", "valeurs_formulaire"]

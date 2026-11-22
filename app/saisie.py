"""Lecture et validation des formulaires, partagées par l'espace chirurgien et l'espace admin."""
import re
from datetime import date

from . import referentiels as R

CASES_A_COCHER = {
    "cicatrice_cheloide",
    "cicatrice_suintement",
    "cicatrice_saignement",
    "cicatrice_oedeme",
    "cicatrice_erytheme",
    "symptome_douleur_persistante",
    "symptome_reapparition_oedeme",
}


class Lecteur:
    def __init__(self, form):
        self.form = form
        self.erreurs = {}

    def _brut(self, nom):
        return (self.form.get(nom) or "").strip()

    def texte(self, nom, requis=False, maxi=2000):
        v = self._brut(nom)
        if not v:
            if requis:
                self.erreurs[nom] = "Champ obligatoire."
            return None
        if len(v) > maxi:
            self.erreurs[nom] = f"{maxi} caractères maximum."
        return v

    def choix(self, nom, options, requis=True):
        v = self._brut(nom)
        if not v:
            if requis:
                self.erreurs[nom] = "Faites un choix."
            return None
        if v not in {str(c) for c, _ in options}:
            self.erreurs[nom] = "Choix invalide."
            return None
        return v

    def entier(self, nom, mini, maxi, requis=True):
        v = self._brut(nom)
        if not v:
            if requis:
                self.erreurs[nom] = "Champ obligatoire."
            return None
        try:
            n = int(v)
        except ValueError:
            self.erreurs[nom] = "Entrez un nombre entier."
            return None
        if n < mini or n > maxi:
            self.erreurs[nom] = f"Valeur attendue entre {mini} et {maxi}."
            return None
        return n

    def decimal(self, nom, mini=0, maxi=500, requis=False):
        v = self._brut(nom).replace(",", ".")
        if not v:
            if requis:
                self.erreurs[nom] = "Champ obligatoire."
            return None
        try:
            n = float(v)
        except ValueError:
            self.erreurs[nom] = "Entrez un nombre (ex. 12,5)."
            return None
        if n < mini or n > maxi:
            self.erreurs[nom] = f"Valeur attendue entre {mini} et {maxi}."
            return None
        return n

    def jour(self, nom, requis=True):
        v = self._brut(nom)
        if not v:
            if requis:
                self.erreurs[nom] = "Date obligatoire."
            return None
        try:
            d = date.fromisoformat(v)
        except ValueError:
            self.erreurs[nom] = "Date invalide."
            return None
        if d > date.today():
            self.erreurs[nom] = "La date ne peut pas être dans le futur."
            return None
        return d

    def oui_non(self, nom, requis=True):
        v = self.choix(nom, R.OUI_NON, requis)
        return None if v is None else v == "oui"

    def case(self, nom):
        return nom in self.form


# ----------------------------------------------------------------- patient

def lire_patient(patient, form):
    L = Lecteur(form)
    initiales = (L.texte("initiales", requis=True, maxi=10) or "").upper().replace(".", "").replace(" ", "")
    if initiales and not re.fullmatch(r"[A-ZÀ-Ÿ\-]{1,6}", initiales):
        L.erreurs["initiales"] = "Lettres uniquement (ex. AD ou A-D)."
    age = L.entier("age_ans", 0, 17)
    niveau = L.choix("niveau_scolaire", R.NIVEAUX_SCOLAIRES)
    consentement = L.oui_non("consentement_parental")
    date_consult = L.jour("date_consultation")
    interv = getattr(patient, "intervention", None)
    if date_consult and interv is not None and interv.date_intervention and date_consult > interv.date_intervention:
        L.erreurs["date_consultation"] = (
            f"L'intervention est enregistrée le {interv.date_intervention:%d/%m/%Y} : "
            "la consultation ne peut pas être postérieure.")
    type_h = L.choix("type_hydrocele", R.TYPES_HYDROCELE)
    cote = L.choix("cote", R.COTES)
    if not L.erreurs:
        patient.initiales = initiales
        patient.age_ans = age
        patient.sexe = R.SEXE_ETUDE  # étude réservée aux garçons : jamais lu du formulaire
        patient.niveau_scolaire = niveau
        patient.consentement_parental = consentement
        patient.date_consultation = date_consult
        patient.type_hydrocele = type_h
        patient.cote = cote
    return L.erreurs


# ------------------------------------------------------------ intervention

def lire_intervention(intervention, form, patient):
    L = Lecteur(form)
    d = L.jour("date_intervention")
    if d and patient.date_consultation and d < patient.date_consultation:
        L.erreurs["date_intervention"] = "L'intervention ne peut pas précéder la consultation d'inclusion."
    dates_visites = [v.date_visite for v in patient.visites if v.statut == "realisee" and v.date_visite]
    if d and dates_visites and d > min(dates_visites):
        L.erreurs["date_intervention"] = (
            f"Une visite est déjà enregistrée le {min(dates_visites):%d/%m/%Y} : "
            "l'intervention ne peut pas être postérieure à une visite.")
    type_c = L.choix("type_chirurgie", R.TYPES_CHIRURGIE)
    voie = L.choix("voie_abord", R.VOIES_ABORD)
    duree = L.entier("duree_minutes", 1, 600)
    compl = L.texte("complications_perop")
    douleur = L.entier("douleur_postop", 0, 10)
    evaluateur = L.choix("douleur_postop_evaluateur", R.EVALUATEURS_DOULEUR)
    hospit = L.entier("duree_hospitalisation_jours", 0, 60)
    if not L.erreurs:
        intervention.date_intervention = d
        intervention.type_chirurgie = type_c
        intervention.voie_abord = voie
        intervention.duree_minutes = duree
        intervention.complications_perop = compl
        intervention.douleur_postop = douleur
        intervention.douleur_postop_evaluateur = evaluateur
        intervention.duree_hospitalisation_jours = hospit
    return L.erreurs


# ------------------------------------------------------------------ visite

def lire_visite(visite, form, echeance, patient):
    L = Lecteur(form)
    valeurs = {}
    d = L.jour("date_visite")
    if d and patient.intervention and d < patient.intervention.date_intervention:
        L.erreurs["date_visite"] = "La visite ne peut pas précéder l'intervention."
    valeurs["date_visite"] = d
    valeurs["douleur_score"] = L.entier("douleur_score", 0, 10)
    valeurs["douleur_evaluateur"] = L.choix("douleur_evaluateur", R.EVALUATEURS_DOULEUR)
    valeurs["complications"] = L.texte("complications")
    valeurs["cicatrice_aspect"] = L.texte("cicatrice_aspect")
    for nom in ("cheloide", "suintement", "saignement", "oedeme", "erytheme"):
        valeurs[f"cicatrice_{nom}"] = L.case(f"cicatrice_{nom}")

    if echeance in R.ECHEANCES_SATISFACTION:
        s = L.choix("satisfaction_score", R.SATISFACTION)
        valeurs["satisfaction_score"] = int(s) if s else None
        valeurs["symptome_douleur_persistante"] = L.case("symptome_douleur_persistante")
        valeurs["symptome_reapparition_oedeme"] = L.case("symptome_reapparition_oedeme")
        valeurs["satisfaction_commentaire"] = L.texte("satisfaction_commentaire")

    if echeance in R.ECHEANCES_ECHOGRAPHIE:
        valeurs["echo_date"] = L.jour("echo_date", requis=False)
        valeurs["echo_epanchement"] = L.oui_non("echo_epanchement")
        if valeurs["echo_epanchement"]:
            valeurs["echo_epanchement_cote"] = L.choix("echo_epanchement_cote", R.COTES_EPANCHEMENT)
            for dim in ("longueur", "largeur", "epaisseur"):
                valeurs[f"echo_epanchement_{dim}"] = L.decimal(f"echo_epanchement_{dim}", 0, 200)
        else:
            valeurs["echo_epanchement_cote"] = None
            for dim in ("longueur", "largeur", "epaisseur"):
                valeurs[f"echo_epanchement_{dim}"] = None
        for cote in ("d", "g"):
            for dim in ("longueur", "largeur", "epaisseur"):
                valeurs[f"echo_testicule_{cote}_{dim}"] = L.decimal(f"echo_testicule_{cote}_{dim}", 0, 100)
            valeurs[f"echo_doppler_{cote}"] = L.choix(f"echo_doppler_{cote}", R.DOPPLER, requis=False)
            valeurs[f"echo_structure_{cote}"] = L.choix(f"echo_structure_{cote}", R.ECHOSTRUCTURE, requis=False)
        valeurs["echo_recidive"] = L.oui_non("echo_recidive")
        valeurs["echo_conclusion"] = L.texte("echo_conclusion")

    if echeance in R.ECHEANCES_ATROPHIE:
        valeurs["atrophie"] = L.oui_non("atrophie")

    if not L.erreurs:
        visite.statut = "realisee"
        for k, v in valeurs.items():
            setattr(visite, k, v)
    return L.erreurs


# chirurgien_id n'est pas gardé : la visite devient une déclaration de l'administratrice.
CHAMPS_GARDES_VISITE = {"id", "patient_id", "echeance", "statut", "cree_le"}


def vider_visite(visite):
    """Efface les données cliniques et l'auteur (visite réalisée repassée en « non réalisée » par l'admin)."""
    for col in visite.__table__.columns:
        if col.name not in CHAMPS_GARDES_VISITE:
            setattr(visite, col.name, False if col.name in CASES_A_COCHER else None)


# ------------------------------------------------- pré-remplissage des formulaires

def valeurs_formulaire(obj):
    """Convertit un objet enregistré en valeurs de formulaire (chaînes)."""
    if obj is None:
        return {}
    sortie = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name)
        if v is None:
            continue
        if col.name in CASES_A_COCHER:
            if v:
                sortie[col.name] = "on"
        elif isinstance(v, bool):
            sortie[col.name] = "oui" if v else "non"
        elif isinstance(v, date):
            sortie[col.name] = v.isoformat()
        elif isinstance(v, float):
            sortie[col.name] = f"{v:g}".replace(".", ",")
        else:
            sortie[col.name] = str(v)
    return sortie

"""Listes de choix et calendrier de suivi de l'étude."""

SEXES = [("M", "Masculin"), ("F", "Féminin")]

NIVEAUX_SCOLAIRES = [
    ("Non scolarisé", "Non scolarisé"),
    ("Préscolaire", "Préscolaire"),
    ("CI", "CI"),
    ("CP", "CP"),
    ("CE1", "CE1"),
    ("CE2", "CE2"),
    ("CM1", "CM1"),
    ("CM2", "CM2"),
]

TYPES_HYDROCELE = [("communicante", "Communicante"), ("non_communicante", "Non communicante")]

COTES = [("droit", "Droit"), ("gauche", "Gauche"), ("bilateral", "Bilatéral")]

TYPES_CHIRURGIE = [("programmee", "Programmée"), ("urgence", "En urgence")]

VOIES_ABORD = [("scrotale", "Scrotale"), ("inguinale", "Inguinale")]

EVALUATEURS_DOULEUR = [("enfant", "L'enfant"), ("medecin", "Le médecin (l'enfant ne peut pas répondre)")]

NOTES_DOULEUR = [(str(i), str(i)) for i in range(11)]

OUI_NON = [("oui", "Oui"), ("non", "Non")]

DOPPLER = [("normale", "Normale"), ("diminuee", "Diminuée"), ("absente", "Absente")]

ECHOSTRUCTURE = [("homogene", "Homogène"), ("heterogene", "Hétérogène")]

COTES_EPANCHEMENT = [("droit", "Droit"), ("gauche", "Gauche"), ("bilateral", "Bilatéral")]

SATISFACTION = [
    ("1", "Très insatisfaits"),
    ("2", "Insatisfaits"),
    ("3", "Ni satisfaits ni insatisfaits"),
    ("4", "Satisfaits"),
    ("5", "Très satisfaits"),
]

# Code, libellé, nombre de jours après l'intervention
ECHEANCES = [
    ("J7", "J7", 7),
    ("M1", "M1 (1 mois)", 30),
    ("M3", "M3 (3 mois)", 90),
    ("M6", "M6 (6 mois)", 180),
]
CODES_ECHEANCES = [c for c, _, _ in ECHEANCES]
JOURS_ECHEANCE = {c: j for c, _, j in ECHEANCES}
LIBELLES_ECHEANCE = {c: l for c, l, _ in ECHEANCES}

# Rubriques présentes selon l'échéance (d'après la fiche d'enquête)
ECHEANCES_ECHOGRAPHIE = {"M3", "M6"}
ECHEANCES_SATISFACTION = {"M3", "M6"}
ECHEANCES_ATROPHIE = {"M6"}

COEFFICIENTS_VOLUME = [("0.52", "0,52 (ellipsoïde)"), ("0.71", "0,71 (Lambert)")]


def libelle(options, valeur):
    """Renvoie le libellé d'une valeur codée, ou la valeur elle-même."""
    if valeur is None or valeur == "":
        return ""
    for code, lib in options:
        if str(code) == str(valeur):
            return lib
    return str(valeur)

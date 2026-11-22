"""Calcul des dates de visite et de leur statut."""
from dataclasses import dataclass
from datetime import date, timedelta

from .referentiels import ECHEANCES, JOURS_ECHEANCE

STATUTS = {
    "realisee": "Réalisée",
    "non_realisee": "Non réalisée",
    "a_venir": "À venir",
    "a_faire": "À faire",
    "en_retard": "En retard",
    "attente_intervention": "Intervention non saisie",
}


@dataclass
class EtatVisite:
    patient: object
    echeance: str
    libelle: str
    statut: str
    date_prevue: date | None
    debut_fenetre: date | None
    fin_fenetre: date | None
    apres_fermeture: bool

    @property
    def libelle_statut(self):
        return STATUTS[self.statut]

    @property
    def saisie_possible(self):
        return self.statut in ("a_venir", "a_faire", "en_retard")


def date_prevue(intervention, echeance):
    return intervention.date_intervention + timedelta(days=JOURS_ECHEANCE[echeance])


def etat_visite(patient, echeance, libelle, parametres, aujourdhui=None):
    aujourdhui = aujourdhui or date.today()
    marge = timedelta(days=parametres.marge_jours)
    visite = patient.visite(echeance)
    intervention = patient.intervention

    if intervention is None:
        return EtatVisite(patient, echeance, libelle, "attente_intervention", None, None, None, False)

    prevue = date_prevue(intervention, echeance)
    debut, fin = prevue - marge, prevue + marge
    apres_fermeture = bool(parametres.date_fermeture and prevue > parametres.date_fermeture)

    if visite is not None:
        statut = visite.statut
    elif aujourdhui < debut:
        statut = "a_venir"
    elif aujourdhui <= fin:
        statut = "a_faire"
    else:
        statut = "en_retard"
    return EtatVisite(patient, echeance, libelle, statut, prevue, debut, fin, apres_fermeture)


def etats_patient(patient, parametres, aujourdhui=None):
    return [etat_visite(patient, c, l, parametres, aujourdhui) for c, l, _ in ECHEANCES]


def ecart_jours(visite):
    """Écart entre la date réelle de la visite et la date prévue (en jours)."""
    p = visite.patient
    if not visite.date_visite or p.intervention is None:
        return None
    return (visite.date_visite - date_prevue(p.intervention, visite.echeance)).days


def hors_fenetre(patient, echeance, jour, parametres):
    if patient.intervention is None or jour is None:
        return False
    prevue = date_prevue(patient.intervention, echeance)
    return abs((jour - prevue).days) > parametres.marge_jours

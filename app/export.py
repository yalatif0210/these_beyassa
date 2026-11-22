"""Export des données (une ligne par patient) et dictionnaire des variables.

Deux formats : un classeur Excel (.xlsx, valeurs typées, dictionnaire en deuxième feuille) et un CSV
pour R, SPSS ou Stata. Les colonnes sont définies une seule fois, dans colonnes().
"""
import csv
import io
from datetime import date

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import referentiels as R
from .planning import date_prevue, ecart_jours


def _b(v):
    return "" if v is None else (1 if v else 0)


def colonnes(coef):
    """Liste (nom, description, fonction) : une seule source pour les données et le dictionnaire."""
    cols = [
        ("numero", "Numéro patient", lambda p: p.numero),
        ("initiales", "Initiales", lambda p: p.initiales),
        ("age_ans", "Âge à l'inclusion (ans)", lambda p: p.age_ans),
        ("niveau_scolaire", "Niveau scolaire", lambda p: p.niveau_scolaire),
        ("consentement_parental", "Consentement parental donné (1 oui, 0 non)", lambda p: _b(p.consentement_parental)),
        ("date_consultation", "Date de la consultation d'inclusion", lambda p: p.date_consultation),
        ("type_hydrocele", "Type d'hydrocèle (communicante, non_communicante)", lambda p: p.type_hydrocele),
        ("cote", "Côté de l'hydrocèle (droit, gauche, bilateral)", lambda p: p.cote),
        ("chirurgien_inclusion", "Chirurgien ayant saisi l'inclusion", lambda p: p.chirurgien.nom if p.chirurgien else ""),
    ]

    def i(attr, transf=None):
        def f(p):
            if p.intervention is None:
                return ""
            v = getattr(p.intervention, attr)
            return transf(v) if transf else v
        return f

    cols += [
        ("date_intervention", "Date de l'intervention", i("date_intervention")),
        ("type_chirurgie", "Chirurgie (programmee, urgence)", i("type_chirurgie")),
        ("voie_abord", "Voie d'abord (scrotale, inguinale)", i("voie_abord")),
        ("duree_intervention_min", "Durée de l'intervention, de la fin de l'installation au pansement (min)", i("duree_minutes")),
        ("complications_perop", "Complications pendant l'intervention (texte libre)", i("complications_perop")),
        ("douleur_postop", "Douleur post-opératoire immédiate (0 à 10)", i("douleur_postop")),
        ("douleur_postop_evaluateur", "Évaluateur de la douleur post-opératoire (enfant, medecin)", i("douleur_postop_evaluateur")),
        ("duree_hospitalisation_j", "Durée d'hospitalisation (jours, 0 = sortie le jour même)", i("duree_hospitalisation_jours")),
        ("chirurgien_intervention", "Chirurgien ayant saisi l'intervention",
         lambda p: p.intervention.chirurgien.nom if p.intervention and p.intervention.chirurgien else ""),
    ]

    for code, libelle, _ in R.ECHEANCES:
        def v(attr, code=code, transf=None, clinique=True):
            def f(p):
                vis = p.visite(code)
                if vis is None or (clinique and vis.statut != "realisee"):
                    return ""
                val = attr(vis) if callable(attr) else getattr(vis, attr)
                return transf(val) if transf else val
            return f

        x = code
        cols += [
            (f"{x}_statut", f"{libelle} : statut (realisee, non_realisee, vide = non saisie)", v("statut", clinique=False)),
            (f"{x}_date_prevue", f"{libelle} : date prévue",
             lambda p, code=code: date_prevue(p.intervention, code) if p.intervention else ""),
            (f"{x}_date", f"{libelle} : date réelle de la visite", v("date_visite")),
            (f"{x}_ecart_j", f"{libelle} : écart entre date réelle et date prévue (jours)", v(ecart_jours)),
            (f"{x}_douleur", f"{libelle} : douleur (0 à 10)", v("douleur_score")),
            (f"{x}_douleur_evaluateur", f"{libelle} : évaluateur de la douleur", v("douleur_evaluateur")),
            (f"{x}_complications", f"{libelle} : complications (texte libre)", v("complications")),
            (f"{x}_cicatrice_aspect", f"{libelle} : aspect de la cicatrice (texte libre)", v("cicatrice_aspect")),
        ]
        for nom, lib in (("cheloide", "chéloïde"), ("suintement", "suintement"), ("saignement", "sang"),
                         ("oedeme", "œdème périlésionnel"), ("erytheme", "érythème périlésionnel")):
            cols.append((f"{x}_cicatrice_{nom}", f"{libelle} : {lib} (1 oui, 0 non)",
                         v(f"cicatrice_{nom}", transf=_b)))
        if code in R.ECHEANCES_SATISFACTION:
            cols += [
                (f"{x}_satisfaction", f"{libelle} : satisfaction parentale (1 très insatisfaits à 5 très satisfaits)", v("satisfaction_score")),
                (f"{x}_symptome_douleur", f"{libelle} : douleur persistante à la maison (1 oui, 0 non)", v("symptome_douleur_persistante", transf=_b)),
                (f"{x}_symptome_oedeme", f"{libelle} : réapparition de l'œdème à la maison (1 oui, 0 non)", v("symptome_reapparition_oedeme", transf=_b)),
                (f"{x}_satisfaction_commentaire", f"{libelle} : commentaire des parents", v("satisfaction_commentaire")),
            ]
        if code in R.ECHEANCES_ECHOGRAPHIE:
            cols += [
                (f"{x}_echo_date", f"{libelle} : date de l'échographie", v("echo_date")),
                (f"{x}_echo_epanchement", f"{libelle} : épanchement liquidien (1 oui, 0 non)", v("echo_epanchement", transf=_b)),
                (f"{x}_echo_epanchement_cote", f"{libelle} : côté de l'épanchement", v("echo_epanchement_cote")),
                (f"{x}_echo_epanchement_L_mm", f"{libelle} : épanchement, longueur (mm)", v("echo_epanchement_longueur")),
                (f"{x}_echo_epanchement_l_mm", f"{libelle} : épanchement, largeur (mm)", v("echo_epanchement_largeur")),
                (f"{x}_echo_epanchement_e_mm", f"{libelle} : épanchement, épaisseur (mm)", v("echo_epanchement_epaisseur")),
                (f"{x}_echo_epanchement_vol_ml", f"{libelle} : volume de l'épanchement (mL, coefficient {coef})",
                 v(lambda vis: vis.volume_epanchement(coef))),
            ]
            for c, nom_cote in (("d", "droit"), ("g", "gauche")):
                cols += [
                    (f"{x}_echo_testicule_{c}_L_mm", f"{libelle} : testicule {nom_cote}, longueur (mm)", v(f"echo_testicule_{c}_longueur")),
                    (f"{x}_echo_testicule_{c}_l_mm", f"{libelle} : testicule {nom_cote}, largeur (mm)", v(f"echo_testicule_{c}_largeur")),
                    (f"{x}_echo_testicule_{c}_e_mm", f"{libelle} : testicule {nom_cote}, épaisseur (mm)", v(f"echo_testicule_{c}_epaisseur")),
                    (f"{x}_echo_testicule_{c}_vol_ml", f"{libelle} : volume du testicule {nom_cote} (mL, coefficient {coef})",
                     v(lambda vis, c=c: vis.volume_testicule(c, coef))),
                    (f"{x}_echo_doppler_{c}", f"{libelle} : vascularisation Doppler, testicule {nom_cote}", v(f"echo_doppler_{c}")),
                    (f"{x}_echo_structure_{c}", f"{libelle} : échostructure, testicule {nom_cote}", v(f"echo_structure_{c}")),
                ]
            cols += [
                (f"{x}_echo_rapport_volumes", f"{libelle} : volume testicule opéré / côté opposé (hydrocèle unilatérale)",
                 v(lambda vis: vis.rapport_volumes(coef))),
                (f"{x}_recidive", f"{libelle} : récidive (1 oui, 0 non)", v("echo_recidive", transf=_b)),
                (f"{x}_echo_conclusion", f"{libelle} : conclusion de l'échographie", v("echo_conclusion")),
            ]
        if code in R.ECHEANCES_ATROPHIE:
            cols.append((f"{x}_atrophie", f"{libelle} : atrophie testiculaire (1 oui, 0 non)", v("atrophie", transf=_b)))
        cols.append((f"{x}_chirurgien", f"{libelle} : chirurgien ayant saisi la visite",
                     v(lambda vis: vis.chirurgien.nom if vis.chirurgien else "", clinique=False)))
    return cols


def _format_csv(val):
    """Valeur pour le CSV R/SPSS : dates ISO, point décimal, texte brut."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if isinstance(val, float):
        return f"{val:g}"
    return val


def csv_donnees(patients, coef):
    """CSV pour R, SPSS ou Stata : séparateur virgule, point décimal, UTF-8 sans BOM."""
    cols = colonnes(coef)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in cols])
    for p in patients:
        w.writerow([_format_csv(f(p)) for _, _, f in cols])
    return buf.getvalue()


def csv_dictionnaire(coef):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["variable", "description"])
    for nom, desc, _ in colonnes(coef):
        w.writerow([nom, desc])
    return buf.getvalue()


# ------------------------------------------------------------------ Excel (.xlsx)

TYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ecrire(ws, ligne, col, val):
    """Écrit une valeur avec son vrai type : nombre, date ou texte."""
    if val is None or val == "":
        return
    if isinstance(val, bool):
        val = int(val)
    if isinstance(val, str):
        # Caractères de contrôle (copier-coller) : interdits dans un fichier xlsx.
        cellule = ws.cell(ligne, col, ILLEGAL_CHARACTERS_RE.sub("", val))
        # Toujours du texte, jamais une formule : openpyxl ferait de « =... » une formule,
        # et Excel interpréterait « - léger hématome » ou « - 2+3 ».
        cellule.data_type = "s"
    elif isinstance(val, date):
        cellule = ws.cell(ligne, col, val)
        cellule.number_format = "DD/MM/YYYY"
    else:
        ws.cell(ligne, col, val)


def _entete(ws, noms, largeurs):
    gras = Font(bold=True)
    for j, (nom, largeur) in enumerate(zip(noms, largeurs), start=1):
        _ecrire(ws, 1, j, nom)
        ws.cell(1, j).font = gras
        ws.column_dimensions[get_column_letter(j)].width = largeur


def xlsx_donnees(patients, coef):
    """Classeur Excel : feuille « Données » (une ligne par patient) et feuille « Dictionnaire »."""
    cols = colonnes(coef)
    wb = Workbook()
    wb.properties.creator = "Beyassa"

    ws = wb.active
    ws.title = "Données"
    _entete(ws, [c[0] for c in cols], [min(max(len(c[0]) + 2, 11), 32) for c in cols])
    for i, p in enumerate(patients, start=2):
        for j, (_, _, f) in enumerate(cols, start=1):
            _ecrire(ws, i, j, f(p))
    ws.freeze_panes = "B2"  # en-tête et numéro du patient toujours visibles
    ws.auto_filter.ref = ws.dimensions

    dico = wb.create_sheet("Dictionnaire")
    _entete(dico, ["variable", "description"], [32, 100])
    for i, (nom, desc, _) in enumerate(cols, start=2):
        _ecrire(dico, i, 1, nom)
        _ecrire(dico, i, 2, desc)
    dico.freeze_panes = "A2"

    sortie = io.BytesIO()
    wb.save(sortie)
    return sortie.getvalue()

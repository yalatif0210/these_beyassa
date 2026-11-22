from datetime import date, timedelta

from app.models import Parametres, Patient, Visite, db

INCLUSION = {
    "initiales": "a.d", "age_ans": "4", "sexe": "M", "niveau_scolaire": "Préscolaire",
    "consentement_parental": "oui", "date_consultation": (date.today() - timedelta(days=100)).isoformat(),
    "type_hydrocele": "communicante", "cote": "droit",
}


def intervention(jours_avant=95):
    return {
        "date_intervention": (date.today() - timedelta(days=jours_avant)).isoformat(),
        "type_chirurgie": "programmee", "voie_abord": "scrotale", "duree_minutes": "25",
        "douleur_postop": "3", "douleur_postop_evaluateur": "medecin", "duree_hospitalisation_jours": "0",
    }


def creer_patient(chir, **surcharge):
    data = {**INCLUSION, **surcharge}
    r = chir.post("/nouveau", data=data)
    assert r.status_code == 200
    return r


# ------------------------------------------------------------------- accès

def test_sans_qr_code_pas_d_acces(app):
    c = app.test_client()
    r = c.get("/")
    assert r.status_code == 302 and "/bienvenue" in r.location
    assert "scannez le QR code" in c.get("/bienvenue").get_data(as_text=True)


def test_mauvais_jeton_refuse(app):
    r = app.test_client().get("/acces/faux")
    assert r.status_code == 403


def test_scan_puis_choix_du_nom(app, jeton):
    c = app.test_client()
    r = c.get(f"/acces/{jeton}")
    assert r.status_code == 302 and jeton not in r.location
    r = c.get("/")
    assert "/qui-etes-vous" in r.location
    page = c.get("/qui-etes-vous").get_data(as_text=True)
    assert "Dr Test" in page and "Dr Inactif" not in page


def test_nouveau_qr_invalide_l_ancien(app, chir, adm):
    assert chir.get("/").status_code == 200
    adm.post("/admin/parametres/nouveau-qr")
    assert chir.get("/").status_code == 302


def test_entetes_de_securite(chir):
    r = chir.get("/")
    assert r.headers["X-Robots-Tag"].startswith("noindex")
    assert r.headers["Referrer-Policy"] == "no-referrer"


# ---------------------------------------------------------------- parcours

def test_parcours_complet(app, chir):
    r = creer_patient(chir)
    assert "HYD-001" in r.get_data(as_text=True)
    with app.app_context():
        p = Patient.query.one()
        assert p.initiales == "AD" and p.chirurgien.nom == "Dr Test"

    r = chir.post("/patient/HYD-001/intervention", data=intervention())
    assert r.status_code == 302
    # Deuxième saisie refusée côté chirurgien
    r = chir.post("/patient/HYD-001/intervention", data=intervention(), follow_redirects=True)
    assert "déjà saisie" in r.get_data(as_text=True)

    page = chir.get("/patient/HYD-001").get_data(as_text=True)
    assert "En retard" in page  # J7 et M1 dépassés, rien saisi

    j7 = {"date_visite": (date.today() - timedelta(days=88)).isoformat(), "douleur_score": "1",
          "douleur_evaluateur": "enfant", "cicatrice_cheloide": "on"}
    assert chir.post("/patient/HYD-001/visite/J7", data=j7).status_code == 302
    assert chir.post("/patient/HYD-001/visite/M1", data={"action": "non_realisee"}).status_code == 302

    m3 = {"date_visite": (date.today() - timedelta(days=2)).isoformat(), "douleur_score": "0",
          "douleur_evaluateur": "enfant", "echo_epanchement": "oui", "echo_epanchement_cote": "droit",
          "echo_epanchement_longueur": "20", "echo_epanchement_largeur": "10", "echo_epanchement_epaisseur": "5",
          "echo_testicule_d_longueur": "15", "echo_testicule_d_largeur": "8", "echo_testicule_d_epaisseur": "7,5",
          "echo_testicule_g_longueur": "16", "echo_testicule_g_largeur": "9", "echo_testicule_g_epaisseur": "8",
          "echo_recidive": "non", "satisfaction_score": "5", "symptome_douleur_persistante": "on"}
    r = chir.post("/patient/HYD-001/visite/M3", data=m3)
    assert r.status_code == 302, r.get_data(as_text=True)

    with app.app_context():
        p = Patient.query.one()
        assert p.visite("J7").cicatrice_cheloide is True
        assert p.visite("M1").statut == "non_realisee"
        v = p.visite("M3")
        assert v.echo_testicule_d_epaisseur == 7.5
        assert v.volume_epanchement(0.71) == round(20 * 10 * 5 * 0.71 / 1000, 2)
        assert v.rapport_volumes(0.71) == round((15 * 8 * 7.5) / (16 * 9 * 8), 2)
        assert v.satisfaction_score == 5 and v.symptome_douleur_persistante


def test_champs_obligatoires(chir):
    r = chir.post("/nouveau", data={"initiales": "AB"})
    page = r.get_data(as_text=True)
    assert "Certains champs sont à corriger" in page
    assert "Faites un choix." in page


def test_m3_exige_recidive_et_satisfaction(chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention())
    r = chir.post("/patient/HYD-001/visite/M3", data={
        "date_visite": date.today().isoformat(), "douleur_score": "0", "douleur_evaluateur": "enfant"})
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert 'id="champ-echo_recidive"' in page and "Faites un choix." in page


def test_visite_avant_intervention_refusee(chir):
    creer_patient(chir)
    r = chir.get("/patient/HYD-001/visite/J7", follow_redirects=True)
    assert "Saisissez d&#39;abord l&#39;intervention" in r.get_data(as_text=True)


def test_alerte_doublon(app, chir):
    creer_patient(chir)
    r = creer_patient(chir, age_ans="5")
    assert "existe peut-être déjà" in r.get_data(as_text=True)
    with app.app_context():
        assert Patient.query.count() == 1
    r = chir.post("/nouveau", data={**INCLUSION, "age_ans": "5", "confirmer_nouveau": "1"})
    assert "HYD-002" in r.get_data(as_text=True)


def test_recherche(chir):
    creer_patient(chir)
    for q in ("HYD-001", "hyd001", "1", "001", "ad", "A.D"):
        assert "HYD-001" in chir.get("/recherche", query_string={"q": q}).get_data(as_text=True), q
    assert "Aucun patient trouvé" in chir.get("/recherche?q=ZZ").get_data(as_text=True)


def test_recherche_ne_montre_pas_de_donnees_cliniques(chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention())
    page = chir.get("/recherche?q=1").get_data(as_text=True)
    assert "Scrotale" not in page and "scrotale" not in page


def test_statuts_et_marge(app):
    from app.planning import etat_visite
    with app.app_context():
        p = Parametres.courants()
        p.marge_jours = 3

        class I:  # intervention factice
            date_intervention = date(2026, 1, 1)

        class P:
            intervention = I()
            def visite(self, e):
                return None

        e = etat_visite(P(), "J7", "J7", p, aujourdhui=date(2026, 1, 4))
        assert e.statut == "a_venir"
        e = etat_visite(P(), "J7", "J7", p, aujourdhui=date(2026, 1, 5))
        assert e.statut == "a_faire"
        e = etat_visite(P(), "J7", "J7", p, aujourdhui=date(2026, 1, 11))
        assert e.statut == "a_faire"
        e = etat_visite(P(), "J7", "J7", p, aujourdhui=date(2026, 1, 12))
        assert e.statut == "en_retard"


# ------------------------------------------------------------------- admin

def test_admin_protege(app):
    r = app.test_client().get("/admin/")
    assert r.status_code == 302 and "/admin/connexion" in r.location


def test_admin_mauvais_mot_de_passe(app):
    c = app.test_client()
    r = c.post("/admin/connexion", data={"identifiant": "admin", "mot_de_passe": "x"})
    assert "incorrect" in r.get_data(as_text=True)


def test_admin_pages(adm, chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention())
    for url in ("/admin/", "/admin/patients", "/admin/patient/HYD-001", "/admin/chirurgiens",
                "/admin/parametres", "/admin/affiche", "/admin/export", "/admin/mot-de-passe",
                "/admin/patient/HYD-001/visite/M6", "/admin/patient/HYD-001/modifier"):
        r = adm.get(url)
        assert r.status_code == 200, url
    assert "<svg" in adm.get("/admin/parametres").get_data(as_text=True)


def test_admin_corrige_et_efface(app, adm, chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention())
    r = adm.post("/admin/patient/HYD-001/intervention", data={**intervention(), "voie_abord": "inguinale"})
    assert r.status_code == 302
    chir.post("/patient/HYD-001/visite/J7", data={"action": "non_realisee"})
    adm.post("/admin/patient/HYD-001/visite/J7/effacer")
    with app.app_context():
        p = Patient.query.one()
        assert p.intervention.voie_abord == "inguinale"
        assert Visite.query.count() == 0


def test_admin_supprime_patient(app, adm, chir):
    creer_patient(chir)
    adm.post("/admin/patient/HYD-001/supprimer", data={"confirmation": "mauvais"})
    with app.app_context():
        assert Patient.query.count() == 1
    adm.post("/admin/patient/HYD-001/supprimer", data={"confirmation": "HYD-001"})
    with app.app_context():
        assert Patient.query.count() == 0


def test_parametres(app, adm):
    r = adm.post("/admin/parametres", data={"marge_jours": "4", "objectif_patients": "60",
                                            "coefficient_volume": "0.52", "date_ouverture": "2026-12-01",
                                            "date_fermeture": "2027-10-01"})
    assert r.status_code == 302
    with app.app_context():
        p = Parametres.courants()
        assert p.marge_jours == 4 and p.coefficient_volume == 0.52


def test_chirurgiens(app, adm):
    adm.post("/admin/chirurgiens", data={"nom": "Dr  Ndiaye"})
    r = adm.post("/admin/chirurgiens", data={"nom": "dr ndiaye"}, follow_redirects=True)
    assert "existe déjà" in r.get_data(as_text=True)


def test_export(adm, chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention())
    r = adm.get("/admin/export/donnees.csv?style=excel")
    txt = r.get_data(as_text=True)
    assert txt.startswith("﻿numero;initiales")
    lignes = txt.strip().splitlines()
    assert len(lignes) == 2
    assert len(lignes[0].split(";")) == len(lignes[1].split(";"))
    std = adm.get("/admin/export/donnees.csv?style=standard").get_data(as_text=True)
    assert std.startswith("numero,initiales")
    dico = adm.get("/admin/export/dictionnaire.csv").get_data(as_text=True)
    assert "M6_atrophie" in dico and "voie_abord" in dico

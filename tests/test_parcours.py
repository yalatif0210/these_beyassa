from datetime import date, timedelta

from app.models import Parametres, Patient, Visite, db

INCLUSION = {
    "initiales": "a.d", "age_ans": "4", "niveau_scolaire": "Préscolaire",
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
    r = chir.post("/nouveau", data=data, follow_redirects=True)
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
    r = chir.post("/nouveau", data={**INCLUSION, "age_ans": "5", "confirmer_nouveau": "1"}, follow_redirects=True)
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


# ------------------------------------------------- verrouillage du nom

def _id_chirurgien(app, nom):
    from app.models import Chirurgien
    with app.app_context():
        c = Chirurgien.query.filter_by(nom=nom).first()
        if c is None:
            c = Chirurgien(nom=nom)
            db.session.add(c)
            db.session.commit()
        return c.id


def test_nom_modifiable_avant_la_premiere_saisie(chir):
    r = chir.get("/changer-de-nom")
    assert "/qui-etes-vous" in r.location


def test_nom_verrouille_apres_la_premiere_saisie(app, chir):
    autre = _id_chirurgien(app, "Dr Autre")
    creer_patient(chir)
    r = chir.get("/changer-de-nom")
    assert r.status_code == 302 and r.location.endswith("/")
    assert "verrouillé" in chir.get("/").get_data(as_text=True)
    # Même en envoyant directement le formulaire, le nom ne change pas.
    chir.post("/qui-etes-vous", data={"chirurgien_id": autre})
    creer_patient(chir, initiales="ZZ", age_ans="8")
    with app.app_context():
        auteurs = {p.chirurgien.nom for p in Patient.query.all()}
    assert auteurs == {"Dr Test"}


def test_admin_libere_les_telephones(app, chir, adm):
    autre = _id_chirurgien(app, "Dr Autre")
    creer_patient(chir)
    cid = _id_chirurgien(app, "Dr Test")
    adm.post(f"/admin/chirurgiens/{cid}/liberer")
    assert "/qui-etes-vous" in chir.get("/").location
    chir.post("/qui-etes-vous", data={"chirurgien_id": autre})
    creer_patient(chir, initiales="ZZ", age_ans="8")
    with app.app_context():
        par_initiales = {p.initiales: p.chirurgien.nom for p in Patient.query.all()}
    # La saisie déjà enregistrée garde son auteur.
    assert par_initiales == {"AD": "Dr Test", "ZZ": "Dr Autre"}


# ---------------------------------------------------------- brouillons

def test_brouillon_sauve_puis_restaure(chir):
    r = chir.post("/brouillon", data={"_cle": "nouveau", "_page": "p1", "initiales": "QX", "age_ans": "6"})
    assert r.status_code == 204
    page = chir.get("/nouveau").get_data(as_text=True)
    assert "Saisie en cours restaurée" in page and 'value="QX"' in page


def test_brouillon_clos_apres_enregistrement(app, chir):
    chir.post("/brouillon", data={"_cle": "nouveau", "_page": "p1", "initiales": "AD"})
    creer_patient(chir, _page="p1")
    # Une sauvegarde automatique partie juste avant l'envoi arrive après : elle est ignorée.
    chir.post("/brouillon", data={"_cle": "nouveau", "_page": "p1", "initiales": "AD"})
    page = chir.get("/nouveau").get_data(as_text=True)
    assert "Saisie en cours restaurée" not in page


def test_brouillon_conserve_si_formulaire_incomplet(chir):
    chir.post("/nouveau", data={"initiales": "RT", "_page": "p2"})
    page = chir.get("/nouveau").get_data(as_text=True)
    assert "Saisie en cours restaurée" in page and 'value="RT"' in page


def test_brouillon_visite_et_effacement(app, chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention(95))
    cle = "visite:HYD-001:J7"
    chir.post("/brouillon", data={"_cle": cle, "_page": "p3", "complications": "léger œdème"})
    assert "léger œdème" in chir.get("/patient/HYD-001/visite/J7").get_data(as_text=True)
    chir.post("/brouillon/effacer", data={"_cle": cle})
    assert "léger œdème" not in chir.get("/patient/HYD-001/visite/J7").get_data(as_text=True)


def test_brouillon_cle_invalide(chir):
    assert chir.post("/brouillon", data={"_cle": "../admin"}).status_code == 400
    assert chir.post("/brouillon", data={"_cle": "visite:HYD-001:X9"}).status_code == 400


def test_brouillon_exige_le_qr_code(app):
    r = app.test_client().post("/brouillon", data={"_cle": "nouveau"})
    assert r.status_code == 302


def test_brouillons_propres_a_chaque_chirurgien(app, chir, jeton):
    chir.post("/brouillon", data={"_cle": "nouveau", "_page": "p1", "initiales": "QX"})
    autre = app.test_client()
    autre.get(f"/acces/{jeton}")
    autre.post("/qui-etes-vous", data={"chirurgien_id": _id_chirurgien(app, "Dr Autre")})
    assert "QX" not in autre.get("/nouveau").get_data(as_text=True)


def test_suppression_patient_efface_ses_brouillons(app, adm, chir):
    from app.models import Brouillon
    creer_patient(chir)
    chir.post("/brouillon", data={"_cle": "intervention:HYD-001", "_page": "p4", "duree_minutes": "20"})
    adm.post("/admin/patient/HYD-001/supprimer", data={"confirmation": "HYD-001"})
    with app.app_context():
        assert Brouillon.query.filter(Brouillon.cle.like("%HYD-001%")).count() == 0


# ------------------------------------------- idempotence (envois rejoués)

JETON = "0123456789abcdef"


def test_nouveau_patient_rejoue_sans_doublon(app, chir):
    data = {**INCLUSION, "_page": JETON}
    r1 = chir.post("/nouveau", data=data)
    r2 = chir.post("/nouveau", data=data)
    assert r1.status_code == 302 and r2.status_code == 302
    assert r2.location == r1.location and r1.location.endswith("/patient/HYD-001/enregistre")
    with app.app_context():
        assert Patient.query.count() == 1
    assert "aucun doublon" in chir.get(r2.location).get_data(as_text=True)


def test_rejeu_apres_confirmation_de_doublon(app, chir):
    creer_patient(chir)
    data = {**INCLUSION, "age_ans": "5", "confirmer_nouveau": "1", "_page": JETON}
    chir.post("/nouveau", data=data)
    chir.post("/nouveau", data=data)
    with app.app_context():
        assert Patient.query.count() == 2


def test_page_de_confirmation_rechargeable(app, chir):
    r = chir.post("/nouveau", data={**INCLUSION, "_page": JETON})
    for _ in range(2):
        assert "HYD-001" in chir.get(r.location).get_data(as_text=True)
    with app.app_context():
        assert Patient.query.count() == 1


def test_intervention_et_visites_rejouees(app, chir):
    creer_patient(chir)
    data = {**intervention(95), "_page": "a" * 16}
    chir.post("/patient/HYD-001/intervention", data=data)
    r = chir.post("/patient/HYD-001/intervention", data=data, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "rien n&#39;a été créé en double" in page and "est déjà saisie" not in page

    j7 = {"date_visite": (date.today() - timedelta(days=88)).isoformat(), "douleur_score": "1",
          "douleur_evaluateur": "enfant", "_page": "b" * 16}
    chir.post("/patient/HYD-001/visite/J7", data=j7)
    r = chir.post("/patient/HYD-001/visite/J7", data=j7, follow_redirects=True)
    assert "rien n&#39;a été créé en double" in r.get_data(as_text=True)

    m1 = {"action": "non_realisee", "_page": "c" * 16}
    chir.post("/patient/HYD-001/visite/M1", data=m1)
    r = chir.post("/patient/HYD-001/visite/M1", data=m1, follow_redirects=True)
    assert "rien n&#39;a été créé en double" in r.get_data(as_text=True)
    with app.app_context():
        assert Visite.query.count() == 2


def test_brouillon_dans_le_bon_ordre(chir):
    def envoyer(seq, initiales):
        return chir.post("/brouillon", data={"_cle": "nouveau", "_page": JETON, "_seq": str(seq), "initiales": initiales})
    assert envoyer(200, "RECENT").status_code == 204
    assert envoyer(100, "ANCIEN").status_code == 204   # arrivé en retard : ignoré
    assert envoyer(200, "REJOUE").status_code == 204   # même numéro renvoyé : ignoré
    page = chir.get("/nouveau").get_data(as_text=True)
    assert 'value="RECENT"' in page and "ANCIEN" not in page and "REJOUE" not in page


def test_admin_activation_rejouee(app, adm):
    cid = _id_chirurgien(app, "Dr Test")
    adm.post(f"/admin/chirurgiens/{cid}/basculer", data={"actif": "0"})
    adm.post(f"/admin/chirurgiens/{cid}/basculer", data={"actif": "0"})
    from app.models import Chirurgien
    with app.app_context():
        assert db.session.get(Chirurgien, cid).actif is False


def test_admin_liberation_rejouee(app, adm):
    from app.models import Chirurgien
    cid = _id_chirurgien(app, "Dr Test")
    adm.post(f"/admin/chirurgiens/{cid}/liberer", data={"generation": "0"})
    adm.post(f"/admin/chirurgiens/{cid}/liberer", data={"generation": "0"})
    with app.app_context():
        assert db.session.get(Chirurgien, cid).generation_session == 1


def test_admin_nouveau_qr_rejoue(app, adm, jeton):
    adm.post("/admin/parametres/nouveau-qr", data={"jeton_actuel": jeton})
    with app.app_context():
        nouveau = Parametres.courants().jeton_acces
    assert nouveau != jeton
    r = adm.post("/admin/parametres/nouveau-qr", data={"jeton_actuel": jeton}, follow_redirects=True)
    assert "déjà été généré" in r.get_data(as_text=True)
    with app.app_context():
        assert Parametres.courants().jeton_acces == nouveau


def test_admin_suppression_rejouee_ne_touche_pas_un_autre_patient(app, adm, chir):
    creer_patient(chir)
    from app.models import empreinte
    with app.app_context():
        ancienne = empreinte(Patient.query.one())
    data = {"confirmation": "HYD-001", "empreinte": ancienne}
    adm.post("/admin/patient/HYD-001/supprimer", data=data)
    r = adm.post("/admin/patient/HYD-001/supprimer", data=data, follow_redirects=True)
    assert "déjà supprimé" in r.get_data(as_text=True)
    # Le numéro est réattribué à un nouvel enfant : un renvoi tardif ne doit pas le supprimer.
    creer_patient(chir, initiales="ZZ", age_ans="8")
    with app.app_context():
        assert Patient.query.one().numero == "HYD-001"
    adm.post("/admin/patient/HYD-001/supprimer", data=data)
    with app.app_context():
        assert Patient.query.count() == 1


def test_admin_effacement_rejoue_ne_touche_pas_une_visite_ressaisie(app, adm, chir):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention(95))
    chir.post("/patient/HYD-001/visite/J7", data={"action": "non_realisee"})
    from app.models import empreinte
    with app.app_context():
        ancienne = empreinte(Visite.query.one())
    adm.post("/admin/patient/HYD-001/visite/J7/effacer", data={"empreinte": ancienne})
    chir.post("/patient/HYD-001/visite/J7", data={"action": "non_realisee"})
    adm.post("/admin/patient/HYD-001/visite/J7/effacer", data={"empreinte": ancienne})
    with app.app_context():
        assert Visite.query.count() == 1


def test_admin_mot_de_passe_rejoue(adm):
    data = {"ancien": "motdepasse", "nouveau": "nouveau-mdp-1", "confirmation": "nouveau-mdp-1"}
    assert adm.post("/admin/mot-de-passe", data=data).status_code == 302
    r = adm.post("/admin/mot-de-passe", data=data, follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "Mot de passe modifié" in page and "incorrect" not in page


# ------------------------------------------------------- guides d'utilisation

def test_chaque_ecran_a_son_guide(app, chir, adm, jeton):
    creer_patient(chir)
    chir.post("/patient/HYD-001/intervention", data=intervention(95))
    anonyme = app.test_client()
    pages = [
        (anonyme, "/bienvenue"), (anonyme, "/admin/connexion"),
        (chir, "/"), (chir, "/recherche?q=1"), (chir, "/nouveau"), (chir, "/patient/HYD-001"),
        (chir, "/patient/HYD-001/enregistre"), (chir, "/patient/HYD-001/visite/M3"),
        (adm, "/admin/"), (adm, "/admin/patients"), (adm, "/admin/patient/HYD-001"),
        (adm, "/admin/patient/HYD-001/modifier"), (adm, "/admin/patient/HYD-001/intervention"),
        (adm, "/admin/patient/HYD-001/visite/J7"), (adm, "/admin/chirurgiens"), (adm, "/admin/parametres"),
        (adm, "/admin/mot-de-passe"), (adm, "/admin/export"),
    ]
    for client, url in pages:
        page = client.get(url).get_data(as_text=True)
        assert 'id="panneau-aide"' in page and "data-ouvrir-aide" in page, url
    # Formulaire d'intervention chirurgien (sur un patient sans intervention) et choix du nom.
    creer_patient(chir, initiales="ZZ", age_ans="8")
    assert 'id="panneau-aide"' in chir.get("/patient/HYD-002/intervention").get_data(as_text=True)
    nouveau = app.test_client()
    nouveau.get(f"/acces/{jeton}")
    assert 'id="panneau-aide"' in nouveau.get("/qui-etes-vous").get_data(as_text=True)


def test_les_guides_parlent_de_l_ecran_affiche(chir, adm):
    assert "Retrouver un patient" in chir.get("/").get_data(as_text=True)
    assert "Exporter les données" in adm.get("/admin/export").get_data(as_text=True)


def test_sexe_non_demande_toujours_masculin(app, chir):
    page = chir.get("/nouveau").get_data(as_text=True)
    assert 'name="sexe"' not in page and "Féminin" not in page
    creer_patient(chir, sexe="F")  # une valeur forgée est ignorée
    with app.app_context():
        assert {p.sexe for p in Patient.query.all()} == {"M"}

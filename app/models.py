import hmac
import secrets
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def maintenant():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def nouveau_jeton():
    return secrets.token_urlsafe(24)


def jetons_egaux(a, b):
    """Comparaison à temps constant ; un jeton non ASCII (lien abîmé) est simplement différent."""
    if not a or not b:
        return False
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def empreinte(obj):
    """Identifie une ligne précise, même si la base réutilise l'identifiant d'une ligne supprimée."""
    return f"{obj.id}-{obj.cree_le:%Y%m%d%H%M%S%f}" if obj is not None and obj.cree_le else ""


def volume_ml(longueur, largeur, epaisseur, coefficient):
    """Volume en mL à partir de trois dimensions en mm."""
    if not longueur or not largeur or not epaisseur:
        return None
    return round(longueur * largeur * epaisseur * coefficient / 1000.0, 2)


class Parametres(db.Model):
    __tablename__ = "parametres"
    id = db.Column(db.Integer, primary_key=True)
    jeton_acces = db.Column(db.String(64), nullable=False, default=nouveau_jeton)
    marge_jours = db.Column(db.Integer, nullable=False, default=5)
    date_ouverture = db.Column(db.Date)
    date_fermeture = db.Column(db.Date)
    coefficient_volume = db.Column(db.Float, nullable=False, default=0.71)
    objectif_patients = db.Column(db.Integer, nullable=False, default=60)

    @staticmethod
    def courants():
        p = db.session.get(Parametres, 1)
        if p is None:
            p = Parametres(id=1)
            db.session.add(p)
            db.session.commit()
        return p


class Admin(db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    identifiant = db.Column(db.String(80), unique=True, nullable=False)
    mot_de_passe_hash = db.Column(db.String(255), nullable=False)

    def definir_mot_de_passe(self, mdp):
        self.mot_de_passe_hash = generate_password_hash(mdp)

    def verifier(self, mdp):
        return check_password_hash(self.mot_de_passe_hash, mdp)


class Chirurgien(db.Model):
    __tablename__ = "chirurgiens"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), unique=True, nullable=False)
    actif = db.Column(db.Boolean, nullable=False, default=True)
    # Incrémenté par l'administratrice pour « libérer » les téléphones de ce chirurgien :
    # les sessions qui portent une ancienne valeur doivent rechoisir le nom.
    generation_session = db.Column(db.Integer, nullable=False, default=0, server_default="0")


class Patient(db.Model):
    __tablename__ = "patients"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, nullable=False, index=True)
    initiales = db.Column(db.String(10), nullable=False, index=True)
    age_ans = db.Column(db.Integer, nullable=False)
    sexe = db.Column(db.String(1), nullable=False)
    niveau_scolaire = db.Column(db.String(30), nullable=False)
    consentement_parental = db.Column(db.Boolean, nullable=False)
    date_consultation = db.Column(db.Date, nullable=False)
    type_hydrocele = db.Column(db.String(30), nullable=False)
    cote = db.Column(db.String(10), nullable=False)
    chirurgien_id = db.Column(db.Integer, db.ForeignKey("chirurgiens.id"))
    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)

    chirurgien = db.relationship("Chirurgien")
    intervention = db.relationship(
        "Intervention", uselist=False, back_populates="patient", cascade="all, delete-orphan"
    )
    visites = db.relationship("Visite", back_populates="patient", cascade="all, delete-orphan")

    def visite(self, echeance):
        for v in self.visites:
            if v.echeance == echeance:
                return v
        return None


class Intervention(db.Model):
    __tablename__ = "interventions"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), unique=True, nullable=False)
    date_intervention = db.Column(db.Date, nullable=False)
    type_chirurgie = db.Column(db.String(20), nullable=False)
    voie_abord = db.Column(db.String(20), nullable=False)
    duree_minutes = db.Column(db.Integer, nullable=False)
    complications_perop = db.Column(db.Text)
    douleur_postop = db.Column(db.Integer, nullable=False)
    douleur_postop_evaluateur = db.Column(db.String(10), nullable=False)
    duree_hospitalisation_jours = db.Column(db.Integer, nullable=False)
    chirurgien_id = db.Column(db.Integer, db.ForeignKey("chirurgiens.id"))
    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)

    patient = db.relationship("Patient", back_populates="intervention")
    chirurgien = db.relationship("Chirurgien")


class Visite(db.Model):
    __tablename__ = "visites"
    __table_args__ = (db.UniqueConstraint("patient_id", "echeance", name="uq_visite_patient_echeance"),)

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    echeance = db.Column(db.String(3), nullable=False)
    statut = db.Column(db.String(15), nullable=False, default="realisee")  # realisee | non_realisee
    date_visite = db.Column(db.Date)
    chirurgien_id = db.Column(db.Integer, db.ForeignKey("chirurgiens.id"))

    # Douleur et complications
    douleur_score = db.Column(db.Integer)
    douleur_evaluateur = db.Column(db.String(10))
    complications = db.Column(db.Text)

    # Cicatrice
    cicatrice_aspect = db.Column(db.Text)
    cicatrice_cheloide = db.Column(db.Boolean, default=False)
    cicatrice_suintement = db.Column(db.Boolean, default=False)
    cicatrice_saignement = db.Column(db.Boolean, default=False)
    cicatrice_oedeme = db.Column(db.Boolean, default=False)
    cicatrice_erytheme = db.Column(db.Boolean, default=False)

    # Satisfaction parentale (M3, M6)
    satisfaction_score = db.Column(db.Integer)
    symptome_douleur_persistante = db.Column(db.Boolean, default=False)
    symptome_reapparition_oedeme = db.Column(db.Boolean, default=False)
    satisfaction_commentaire = db.Column(db.Text)

    # Échographie (M3, M6)
    echo_date = db.Column(db.Date)
    echo_epanchement = db.Column(db.Boolean)
    echo_epanchement_cote = db.Column(db.String(10))
    echo_epanchement_longueur = db.Column(db.Float)
    echo_epanchement_largeur = db.Column(db.Float)
    echo_epanchement_epaisseur = db.Column(db.Float)
    echo_testicule_d_longueur = db.Column(db.Float)
    echo_testicule_d_largeur = db.Column(db.Float)
    echo_testicule_d_epaisseur = db.Column(db.Float)
    echo_testicule_g_longueur = db.Column(db.Float)
    echo_testicule_g_largeur = db.Column(db.Float)
    echo_testicule_g_epaisseur = db.Column(db.Float)
    echo_doppler_d = db.Column(db.String(10))
    echo_doppler_g = db.Column(db.String(10))
    echo_structure_d = db.Column(db.String(12))
    echo_structure_g = db.Column(db.String(12))
    echo_recidive = db.Column(db.Boolean)
    echo_conclusion = db.Column(db.Text)

    # Atrophie testiculaire (M6)
    atrophie = db.Column(db.Boolean)

    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)

    patient = db.relationship("Patient", back_populates="visites")
    chirurgien = db.relationship("Chirurgien")

    def volume_epanchement(self, coef):
        return volume_ml(
            self.echo_epanchement_longueur, self.echo_epanchement_largeur, self.echo_epanchement_epaisseur, coef
        )

    def volume_testicule(self, cote, coef):
        return volume_ml(
            getattr(self, f"echo_testicule_{cote}_longueur"),
            getattr(self, f"echo_testicule_{cote}_largeur"),
            getattr(self, f"echo_testicule_{cote}_epaisseur"),
            coef,
        )

    def rapport_volumes(self, coef):
        """Volume du testicule opéré divisé par celui du côté opposé (hydrocèle unilatérale)."""
        cote = self.patient.cote
        if cote not in ("droit", "gauche"):
            return None
        opere = self.volume_testicule("d" if cote == "droit" else "g", coef)
        oppose = self.volume_testicule("g" if cote == "droit" else "d", coef)
        if not opere or not oppose:
            return None
        return round(opere / oppose, 2)


class Brouillon(db.Model):
    """Saisie en cours d'un chirurgien, enregistrée automatiquement.

    `cle` désigne le formulaire : "nouveau", "intervention:HYD-001" ou "visite:HYD-001:J7".
    `page` identifie l'affichage du formulaire : une fois la saisie enregistrée, le brouillon est
    « clos » et les sauvegardes automatiques encore en route pour cette même page sont ignorées.
    """
    __tablename__ = "brouillons"
    __table_args__ = (db.UniqueConstraint("chirurgien_id", "cle", name="uq_brouillon_chirurgien_cle"),)
    id = db.Column(db.Integer, primary_key=True)
    chirurgien_id = db.Column(db.Integer, db.ForeignKey("chirurgiens.id"), nullable=False)
    cle = db.Column(db.String(60), nullable=False)
    page = db.Column(db.String(32), nullable=False, default="")
    donnees = db.Column(db.Text, nullable=False, default="{}")
    clos = db.Column(db.Boolean, nullable=False, default=False)
    # Horodatage (ms) de la modification côté téléphone : une sauvegarde plus ancienne arrivée
    # en retard n'écrase jamais une plus récente.
    seq = db.Column(db.BigInteger, nullable=False, default=0, server_default="0")
    maj_le = db.Column(db.DateTime, nullable=False, default=maintenant, onupdate=maintenant)


class Envoi(db.Model):
    """Formulaire chirurgien déjà enregistré, identifié par son jeton d'envoi (idempotence).

    Enregistré dans la même transaction que la saisie : si la saisie existe, le jeton aussi.
    Un envoi rejoué avec le même jeton renvoie vers `resultat` sans rien créer.
    """
    __tablename__ = "envois"
    id = db.Column(db.Integer, primary_key=True)
    jeton = db.Column(db.String(32), unique=True, nullable=False)
    chirurgien_id = db.Column(db.Integer, db.ForeignKey("chirurgiens.id"), nullable=False)
    cle = db.Column(db.String(60), nullable=False)
    resultat = db.Column(db.String(200), nullable=False)
    cree_le = db.Column(db.DateTime, nullable=False, default=maintenant)

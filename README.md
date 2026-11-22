# Beyassa

Application web de collecte de données pour la thèse de Dr BEYASSA:
*Étude comparative de l'abord scrotal versus abord inguinal dans la cure chirurgicale de l'hydrocèle de l'enfant*
(service de chirurgie pédiatrique de Thiès).

## Fonctionnement

**Chirurgiens (sans compte)**
1. Ils scannent le QR code affiché dans le service. Le téléphone garde ensuite l'accès.
2. Ils choisissent leur nom une seule fois. Chaque saisie est enregistrée à leur nom.
3. Ils créent un patient (numéro attribué automatiquement, par exemple `HYD-007`, à noter dans le dossier), saisissent l'intervention, puis les visites J7, M1, M3 et M6.
4. Pour les visites, ils retrouvent le patient par son numéro (`7`, `007` ou `HYD-007`) ou par ses initiales.
5. Une information enregistrée ne peut plus être modifiée par les chirurgiens : les corrections passent par l'administratrice.

**Administratrice (compte unique)**, à l'adresse `/admin`
- Tableau de bord : patients inclus, visites à faire, en retard, à venir, prévues après la fermeture.
- Fiche complète de chaque patient, avec correction, effacement d'une visite et suppression d'un doublon.
- Liste des chirurgiens (ajout, désactivation).
- Paramètres : marge autour des visites, dates d'ouverture et de fermeture, objectif de patients, coefficient de volume.
- QR code : affiche imprimable, et génération d'un nouveau QR code si l'ancien a circulé.
- Export CSV (une ligne par patient) pour Excel ou pour R, SPSS et Stata, avec le dictionnaire des variables.

## Lancer en local (Windows, PowerShell)

```powershell
cd C:\Users\ma.admin\Desktop\Projets\beyassa
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:SECRET_KEY = "cle-de-developpement"
$env:ADMIN_IDENTIFIANT = "nguessan"
$env:ADMIN_MOT_DE_PASSE = "motdepasse-local"
$env:BASE_URL = "http://localhost:8000"

flask --app wsgi run --port 8000
```

Sans `DATABASE_URL`, l'application utilise une base SQLite dans `instance/beyassa.db`.

- Espace administrateur : http://localhost:8000/admin
- Lien des chirurgiens (celui du QR code) : `flask --app wsgi lien-acces`
- Créer ou réinitialiser le compte administrateur : `flask --app wsgi creer-admin`

Pour tester la partie chirurgien sur un téléphone du même réseau Wi-Fi, lancer avec `--host 0.0.0.0`, mettre l'adresse IP du PC dans `BASE_URL`, puis scanner le QR code de la page Paramètres.

## Tests

```powershell
pip install pytest
python -m pytest
```

## Déploiement sur un serveur (Docker)

```bash
cp .env.example .env        # puis remplir toutes les valeurs « a_remplacer »
docker compose up -d --build
docker compose logs -f web
```

Trois services démarrent :
- `db` : PostgreSQL 16 ;
- `web` : l'application (Gunicorn), accessible uniquement en local sur le port 8000 ;
- `sauvegarde` : une sauvegarde de la base par jour dans `./sauvegardes`, conservée 30 jours.

Nginx sert l'application en HTTPS : voir `deploy/nginx.conf`, puis `certbot --nginx`.
Le HTTPS est indispensable : avec `COOKIE_SECURISE=true`, les navigateurs n'envoient le cookie de session qu'en HTTPS.

**Restaurer une sauvegarde**
```bash
gunzip -c sauvegardes/beyassa_AAAAMMJJ_HHMM.sql.gz | docker compose exec -T db psql -U beyassa -d beyassa
```

## Mise en service

1. Se connecter à `/admin` avec le compte défini dans `.env`, puis changer le mot de passe.
2. Ajouter les chirurgiens.
3. Régler la marge, les dates d'ouverture et de fermeture, et le coefficient de volume.
4. Imprimer l'affiche du QR code et l'afficher dans le service.

## Sécurité

L'accès des chirurgiens n'a ni compte ni mot de passe, pour faciliter l'adhésion. Les protections sont invisibles pour eux :
- le QR code contient une clé aléatoire impossible à deviner, que l'administratrice peut remplacer en un clic ;
- la clé disparaît de la barre d'adresse juste après le scan, et n'est pas écrite dans les journaux Nginx ;
- la recherche n'affiche aucune donnée clinique ;
- les pages ne sont pas indexées par les moteurs de recherche ;
- le nombre de recherches et de tentatives de connexion par minute est limité ;
- l'enfant n'est identifié que par ses initiales et son numéro.

## Choix à valider

Ces points ne sont pas précisés dans la fiche d'enquête et peuvent être ajustés :
- l'âge est saisi en années entières ;
- la durée d'hospitalisation est saisie en jours (0 = sortie le jour même) ;
- le côté de l'hydrocèle (droit, gauche, bilatéral) a été ajouté à l'inclusion, car l'échographie compare les deux testicules ;
- les complications sont saisies à chaque visite, en texte libre ;
- la marge par défaut est de 5 jours et le coefficient de volume par défaut est 0,71 (modifiables dans les paramètres).

## Structure

```
app/
  __init__.py       création de l'application, sécurité, commandes
  models.py         tables de la base
  referentiels.py   listes de choix et calendrier des visites
  planning.py       dates prévues et statut des visites
  saisie.py         lecture et contrôle des formulaires
  chirurgien.py     espace chirurgien (QR code)
  admin.py          espace administrateur
  export.py         export CSV et dictionnaire des variables
  templates/        pages HTML
  static/style.css  mise en forme
tests/              tests automatisés
deploy/             Nginx et sauvegarde
```

La base est créée automatiquement au premier démarrage. Si la structure des tables change en cours d'étude, il faudra ajouter les colonnes à la main ou mettre en place des migrations (Flask-Migrate).

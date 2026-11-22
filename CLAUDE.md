# CLAUDE.md : contexte du projet Beyassa

## Objet

Beyassa est une application web de collecte de données pour une **thèse de doctorat en médecine** :
*Étude comparative de l'abord scrotal versus abord inguinal dans la cure chirurgicale de l'hydrocèle de l'enfant : efficacité, morbidité et bénéfice fonctionnel, à propos d'une série prospective au service de chirurgie pédiatrique de Thiès (Sénégal).*

Elle remplace la fiche d'enquête papier. Le développeur est Markov. Le « propriétaire » est l'auteur de la thèse : c'est lui qui valide les règles métier. Ne pas modifier une règle métier sans son accord. Proposer, puis attendre la validation.

## État actuel

- Le code est complet et fonctionne : 45 tests pytest passent (`python -m pytest`).
- Les écrans ont été vérifiés sur mobile (390 px) et sur ordinateur, avec des données fictives.
- Rien n'est encore déployé.
- Dépôt git sur la branche `main`, publié sur GitHub : `origin` = https://github.com/yalatif0210/these_beyassa.git. Auteur configuré localement : `yalatif0210`.
- Les tests passent aussi sous Python 3.14 (version installée sur le PC de développement).

## Règles métier validées par le propriétaire

**Utilisation**
- La saisie est faite par les **chirurgiens**, sur leur téléphone, en scannant un **QR code** affiché dans le service. Il y a une connexion internet.
- **Aucun mot de passe pour les chirurgiens** (volonté explicite de favoriser l'adhésion). Les protections doivent rester invisibles pour eux.
- **Une seule administratrice**, Mlle Nguessan, avec un compte. Elle seule voit toutes les données.
- Objectif : 60 patients, inclusion sur 4 mois.

**Inclusion**
- L'étude porte sur les enfants de 1 à 10 ans. L'application ne doit **pas bloquer** la saisie selon l'âge (simple aide affichée).
- Consentement des parents : oui ou non.
- L'enfant est identifié par ses **initiales** uniquement, jamais par son nom. Un numéro `HYD-001`, `HYD-002`… est attribué automatiquement et noté dans le dossier papier.
- Le type d'hydrocèle (communicante ou non) est déterminé à l'examen physique lors de la consultation initiale.
- Niveau scolaire, liste confirmée : Non scolarisé, Préscolaire, CI, CP, CE1, CE2, CM1, CM2.

**Voie d'abord et aveugle**
- La voie d'abord (scrotale ou inguinale) est **choisie par le chirurgien, à son appréciation**. Il n'y a **pas de randomisation**.
- Elle est connue au compte rendu opératoire.
- Les personnes en aveugle sont les **parents**. Les parents n'utilisent pas l'application : **aucun champ n'est masqué** selon le rôle.

**Intervention**
- La durée est mesurée **de la fin de l'installation au pansement, en minutes**.
- Complications : **texte libre**.
- Douleur : échelle de **0 à 10**. On enregistre aussi qui a donné le score, l'enfant ou le médecin (le médecin évalue quand l'enfant ne peut pas répondre).

**Suivi : J7, M1, M3 et M6**
- La date prévue est calculée à partir de la date de l'intervention : 7, 30, 90 et 180 jours.
- **Une seule marge** pour toutes les visites (3 à 5 jours selon le propriétaire). C'est un réglage modifiable par l'administratrice, 5 jours par défaut.
- Visite manquée : on la marque « non réalisée » et on **passe à la suivante**.
- Les rappels apparaissent **sur le tableau de bord de l'administratrice** (pour l'instant). Pas d'envoi par SMS, e-mail ou WhatsApp.
- Cicatrice : aspect (texte), plus cases à cocher pour chéloïde, suintement, sang, œdème périlésionnel et érythème périlésionnel.
- **M3 et M6** : avis des parents (échelle à 5 niveaux), signes remarqués à la maison (douleur persistante, réapparition de l'œdème), commentaire libre.
- **M3 et M6, échographie** (saisie par le chirurgien, liste validée) : date ; épanchement oui/non avec côté et 3 dimensions en mm ; 3 dimensions de chaque testicule ; Doppler et échostructure du côté opéré ; récidive oui/non ; conclusion. Les volumes sont calculés automatiquement : L × l × e × coefficient / 1000, en mL. Le coefficient (0,52 ou 0,71) se règle dans les paramètres, 0,71 par défaut.
- **M6** : atrophie testiculaire oui/non.

**Données**
- Le comité d'éthique et la faculté n'imposent pas de règle de stockage.
- Export CSV, une ligne par patient, en deux formats : Excel (séparateur `;`, virgule décimale, BOM UTF-8) ou R/SPSS (séparateur `,`, point décimal). Les oui/non sont codés 1/0. Un dictionnaire des variables est fourni.

## Choix faits par Claude, encore à valider avec le propriétaire

- L'âge est saisi en années entières.
- La durée d'hospitalisation est saisie en jours (0 = sortie le jour même).
- Le **côté de l'hydrocèle** (droit, gauche, bilatéral) a été ajouté à l'inclusion. Il ne figure pas sur la fiche papier, mais l'échographie en a besoin pour distinguer le côté opéré du côté opposé.
- Les complications sont saisies à chaque visite.
- **Point ouvert important** : le propriétaire a dit « 4 mois pour toute l'étude » puis « l'application pourra rester ouverte 6 mois ». Or, avec des inclusions étalées sur 4 mois, il faut environ 10 mois pour que tous les patients atteignent M6. Le sujet a été signalé mais pas tranché. Les dates d'ouverture et de fermeture sont des réglages, et le tableau de bord liste les visites prévues après la fermeture.

## Architecture

- Python 3.13, Flask 3.1, Flask-SQLAlchemy, Flask-WTF (CSRF), Flask-Limiter, qrcode.
- Pages générées côté serveur (Jinja2), **sans framework JavaScript** : un formulaire léger sur mobile. Le peu de JavaScript utilisé est en ligne dans les templates.
- PostgreSQL 16 en production (`DATABASE_URL`), SQLite dans `instance/` par défaut en local.
- Les tables sont créées par `db.create_all()` au démarrage. **Il n'y a pas de migrations** : tout changement de colonne en cours d'étude demande une migration manuelle ou l'ajout de Flask-Migrate.
- Docker : Gunicorn avec `--preload` et 2 workers. Un service `sauvegarde` fait un `pg_dump` quotidien, conservé 30 jours. Nginx assure le HTTPS (`deploy/nginx.conf`).

```
app/__init__.py      create_app, configuration par variables d'environnement, en-têtes de sécurité, commandes CLI
app/models.py        Parametres (ligne unique id=1), Admin, Chirurgien, Patient, Intervention, Visite, Brouillon, Envoi
app/referentiels.py  listes de choix, échéances, rubriques par échéance (SOURCE UNIQUE des listes)
app/planning.py      date prévue, fenêtre, statut (realisee, non_realisee, a_venir, a_faire, en_retard, attente_intervention)
app/saisie.py        classe Lecteur : lecture et validation des formulaires, partagée entre chirurgien et admin
app/chirurgien.py    blueprint racine : accès par QR code, choix du nom, recherche, création, saisies
app/admin.py         blueprint /admin : tableau de bord, fiches, corrections, chirurgiens, paramètres, QR code, export
app/export.py        colonnes() = source unique pour le CSV et pour le dictionnaire des variables
app/templates/forms/ formulaires partagés (_inclusion, _intervention, _visite), inclus via formulaire.html
app/templates/_macros.html  macros de champs (radios en « pilules », cases, échelle de douleur, dimensions)
app/templates/aide/   guide d'utilisation de chaque écran, nommé <blueprint>_<vue>.html (ex. chirurgien_accueil.html)
```

## Sécurité (sans mot de passe côté chirurgien)

- Le QR code encode `/acces/<jeton>`, un jeton aléatoire `secrets.token_urlsafe(24)` stocké dans `Parametres.jeton_acces`. Il est comparé avec `hmac.compare_digest`.
- Le jeton est placé dans une session permanente (365 jours), puis la page redirige pour qu'il disparaisse de la barre d'adresse. Avec `Referrer-Policy: no-referrer`, il ne fuit pas vers d'autres sites.
- Si l'administratrice régénère le jeton, toutes les sessions des chirurgiens sont invalidées.
- Le nom du chirurgien est choisi une seule fois et gardé en session. Il est enregistré sur chaque saisie (`chirurgien_id`), et aucun écran ne permet de changer l'auteur d'une saisie.
- **Nom verrouillé** : dès la première saisie enregistrée depuis un téléphone (`session["nom_verrouille"]`), ce téléphone ne peut plus changer de nom. L'administratrice peut « libérer les téléphones » d'un chirurgien (`Chirurgien.generation_session` incrémenté : les sessions qui portent une ancienne valeur doivent rechoisir le nom). Effacer les données du navigateur et rescanner le QR code contourne le verrou : c'est une protection contre l'erreur, pas contre la malveillance.
- **Brouillons** : chaque formulaire chirurgien est sauvegardé automatiquement sur le serveur (table `brouillons`, une ligne par chirurgien et par formulaire, clé `nouveau`, `intervention:HYD-001` ou `visite:HYD-001:J7`), 1,5 s après chaque modification et à la mise en arrière-plan (`sendBeacon`). Il est restauré à la réouverture et « clos » dans la même transaction que l'enregistrement ; le champ `_page` fait ignorer une sauvegarde tardive de la même page. La suppression d'un patient efface ses brouillons (son numéro peut être réattribué). Les brouillons ne sont pas exportés.
- La recherche n'affiche ni la voie d'abord ni aucune donnée clinique.
- Les chirurgiens ne peuvent pas modifier une saisie existante. Seule l'administratrice corrige.
- En-têtes `X-Robots-Tag: noindex`, `X-Frame-Options`, `nosniff`, `Cache-Control: no-store`.
- Limites : recherche 30/min, accès 20/min, connexion admin 10/min. Le stockage `memory://` est propre à chaque worker. Passer à Redis si besoin.
- Nginx n'écrit pas `/acces/` dans ses journaux.
- `COOKIE_SECURISE=true` en production (HTTPS obligatoire), `false` en local en HTTP.

## Idempotence (règle pour toute nouvelle opération d'écriture)

Toute requête qui écrit doit pouvoir être rejouée sans effet en double : double appui, rechargement, renvoi du navigateur, réponse perdue pendant une coupure réseau.
- **Saisies chirurgien** (patient, intervention, visite, visite non réalisée) : le formulaire porte un jeton d'envoi `_page` (16 hex, généré à l'affichage). La saisie réussie enregistre ce jeton dans la table `envois` **dans la même transaction** ; un envoi rejoué renvoie vers `Envoi.resultat` sans rien créer. Envois simultanés : la contrainte unique (jeton, `interventions.patient_id`, `uq_visite_patient_echeance`) lève `IntegrityError`, on annule et on renvoie vers le résultat existant.
- **Post/Redirect/Get** : toute création réussie se termine par une redirection (`/patient/<numero>/enregistre` pour un nouveau patient), jamais par l'affichage direct d'une page.
- **Brouillons** : `_seq` (horodatage ms de la modification sur le téléphone) ; le serveur ignore une sauvegarde plus ancienne ou déjà reçue. Une seule sauvegarde en vol ; copie locale « en attente » (localStorage, clé par chirurgien et formulaire) effacée dès la confirmation du serveur, jamais restaurée si la page a déjà été enregistrée.
- **Actions admin** : envoyer l'état visé ou l'élément précis, jamais une bascule. Activer/désactiver envoie `actif=0/1` ; « libérer » envoie la `generation_session` affichée ; nouveau QR envoie le `jeton_actuel` affiché ; supprimer un patient et effacer une visite envoient l'`empreinte` (id + date de création : SQLite réutilise l'id d'une ligne supprimée et un numéro de patient peut être réattribué). Les mises à jour complètes (paramètres, corrections) sont idempotentes par nature.
- Le bouton d'envoi est désactivé pendant l'envoi (`base.html`), mais ce n'est qu'un confort : la garantie est côté serveur.

## Conventions

- **Tout en français** : interface, noms de variables et de fonctions métier, messages, README.
- **Aucun tiret cadratin (caractère Unicode U+2014)** nulle part : code, interface, documentation, messages de commit. Utiliser deux-points, virgules ou parenthèses.
- Garder `referentiels.py` et `export.colonnes()` comme sources uniques. Un nouveau champ demande de modifier : le modèle, `saisie.py`, le formulaire partagé, la fiche admin (`admin/patient.html`), `export.colonnes()` et un test.
- Interface d'abord pensée pour le téléphone : zones tactiles de 44 px minimum, choix en pilules plutôt qu'en listes déroulantes.
- `deploy/sauvegarde.sh` doit rester en fins de ligne LF (voir `.gitattributes`).
- **Chaque écran a son guide** : un nouvel écran demande un fichier `app/templates/aide/<blueprint>_<vue>.html` (le bouton « Aide » n'apparaît que s'il existe) et son ajout dans `test_chaque_ecran_a_son_guide`. Un changement de comportement demande de mettre le guide à jour.

## Commandes utiles

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt pytest
$env:SECRET_KEY="dev"; $env:ADMIN_IDENTIFIANT="nguessan"; $env:ADMIN_MOT_DE_PASSE="motdepasse"; $env:BASE_URL="http://localhost:8000"
flask --app wsgi run --port 8000          # admin : http://localhost:8000/admin
flask --app wsgi lien-acces               # lien encodé dans le QR code (accès chirurgien)
flask --app wsgi creer-admin              # créer ou réinitialiser le compte admin
python -m pytest                          # tests
docker compose up -d --build              # production (après avoir rempli .env à partir de .env.example)
```

## Prochaines étapes possibles

1. Lancer l'application en local et la tester sur un vrai téléphone (`--host 0.0.0.0` et l'IP du PC dans `BASE_URL`).
2. Faire valider par le propriétaire les choix listés plus haut, et trancher la durée d'ouverture.
3. Déployer sur un VPS : Docker, Nginx et certbot.
4. Si l'étude démarre, ajouter Flask-Migrate avant toute évolution du schéma.

# Déploiement de Beyassa sur le VPS dédié (etude.beyassa.org, derrière Cloudflare)

Serveur : `vps-elyon-staging` (169.58.210.138, Ubuntu 26.04), alias SSH déjà configuré sur le PC.
Ce serveur hébergeait jusqu'ici l'environnement de test d'Elyon ERP. Il sera **dédié à Beyassa**.

L'application est servie sur le sous-domaine **`etude.beyassa.org`**. Le domaine principal `beyassa.org` reste libre pour autre chose : le relais refuse tout autre nom. Ce nom est réglé par `DOMAINE` et `BASE_URL` dans `.env`. Il est imprimé dans le QR code : le choisir avant d'imprimer l'affiche.

```
Navigateur ──HTTPS──▶ Cloudflare ──HTTPS (certificat d'origine)──▶ relais nginx :443 ──▶ web (Gunicorn) ──▶ db (PostgreSQL)
                                                                     réseau public        └──────── réseau interne, sans Internet ────────┘
```

Pourquoi ces choix :
- **Cloudflare devant** : le serveur n'est jamais exposé directement. Cloudflare fournit le certificat public, absorbe les attaques et cache l'adresse du serveur.
- **Seules les adresses Cloudflare peuvent joindre le port 443** : le filtre est dans nginx, parce que Docker publie ses ports en contournant le pare-feu `ufw`.
- **Réseau interne sans Internet** : la base, l'application et les sauvegardes ne peuvent ni être jointes de l'extérieur, ni envoyer quoi que ce soit dehors.
- **Certificat d'origine Cloudflare** : il est gratuit, valable 15 ans et n'a jamais besoin d'être renouvelé, contrairement à Let's Encrypt.

---

## Étape 1 : enregistrer le domaine et créer le sous-domaine dans Cloudflare

1. Acheter `beyassa.org` chez un registraire, même si seul le sous-domaine `etude.` est utilisé. Il n'existe pas encore : le DNS public répond « domaine inexistant ».
2. Dans Cloudflare, cliquer sur **Ajouter un domaine** pour `beyassa.org`, puis remplacer les serveurs DNS chez le registraire par ceux indiqués par Cloudflare.
3. **DNS** : créer un enregistrement `A`, nom **`etude`**, valeur `169.58.210.138`, **proxy activé** (nuage orange). Le certificat public gratuit de Cloudflare couvre ce sous-domaine.
4. **SSL/TLS > Vue d'ensemble** : mode **Complet (strict)**. Avec un mode moins strict, Cloudflare accepterait un serveur sans certificat valide.
5. **SSL/TLS > Certificats Edge** : activer **Toujours utiliser HTTPS**, et choisir **TLS 1.2** comme version minimale.
6. **SSL/TLS > Serveur d'origine** : cliquer sur **Créer un certificat** (RSA, noms `beyassa.org` et `*.beyassa.org`, validité 15 ans). `*.beyassa.org` couvre `etude.beyassa.org`.
   - Copier le **certificat** dans un fichier `origine.pem` sur le PC.
   - Copier la **clé privée** dans `origine.key`. Elle n'est affichée qu'une fois.
   - Ne jamais mettre ces fichiers dans git (`deploy/certs/` est exclu) ni les envoyer par messagerie.
7. **Vitesse > Optimisation** : vérifier que **Rocket Loader** est désactivé. Il réécrit le JavaScript des pages et peut casser la sauvegarde automatique des saisies.

---

## Étape 2 : retirer Elyon ERP du serveur ✅ fait le 22/11/2026

Suppression validée par le responsable d'Elyon ERP. Ce qui a été fait, dans l'ordre :

**2.1 Couper le redéploiement automatique.** Le workflow « Déploiement staging » du dépôt `yalatif0210/elyon_erp` (`.github/workflows/deploy-staging.yml`) se lançait après chaque CI réussie sur `dev`. Il se connectait en SSH à ce serveur pour y lancer `docker compose up -d`. Trois verrous ont été posés :
1. Workflow désactivé (`disabled_manually`). Pour le réactiver : `gh workflow enable "Déploiement staging" -R yalatif0210/elyon_erp`.
2. Secret `STAGING_SSH_KEY` supprimé de l'environnement GitHub `staging`. Les autres secrets (`STAGING_SSH_HOST`, `STAGING_SSH_USER`, `STAGING_DEPLOY_PATH`) pointent encore vers ce serveur : à mettre à jour si Elyon ERP reçoit un nouveau serveur de test, avec une nouvelle clé.
3. Clé du pipeline (`elyon-erp-staging-deploy`) révoquée : elle a disparu avec l'utilisateur `deploy` (2.3).

**2.2 Sauvegarde complète**, rapatriée sur le PC et vérifiée par empreintes SHA-256 :
`C:\Users\ma.admin\Documents\sauvegardes_elyon_erp\elyon_sauvegarde_20261122\`

| Fichier | Contenu |
|---|---|
| `base_postgres.sql.gz` | `pg_dumpall` complet (75 tables, marqueur de fin présent) |
| `volume_api_uploads.tar.gz` | fichiers déposés dans l'ERP |
| `volume_redis_data.tar.gz` | données Redis |
| `config_env_et_certs.tar.gz` | `.env` du staging et certificat d'origine Cloudflare d'elyon-trading.com : **contient des secrets**, à garder sur un support protégé |
| `SHA256SUMS` | empreintes (`sha256sum -c SHA256SUMS`) |

Non sauvegardés : le volume `node_modules`, qui se régénère, et le code, qui est sur GitHub. La copie de la sauvegarde laissée sur le serveur a été effacée.

**2.3 Suppression.** Les conteneurs, les volumes, les réseaux et les images d'Elyon ERP ont été supprimés (`docker compose down -v`, puis `docker image prune -a`), ce qui a libéré 2 Go. L'utilisateur `deploy` a été supprimé avec son dossier : code, clé SSH du pipeline et identifiants `ghcr.io`. Aucune tâche planifiée ni règle sudo ne restait.

**2.4 À faire par vous, dans Cloudflare d'elyon-trading.com** : supprimer les enregistrements `staging-erp`, `staging-terrain` et `staging-portail`. Ils pointent encore vers ce serveur et affichent maintenant une erreur.

Reste aussi sur le serveur `~/certs/cloudflare/` (dossier de `christian`) : une copie du certificat d'origine d'Elyon **avec sa clé privée**, déposée en août et également présente dans la sauvegarde. Elle ne sert plus à rien ici : à supprimer (`rm -r ~/certs`) dès que vous le décidez.

---

## Étape 3 : durcir le serveur ✅ fait le 22/11/2026

| Point | État |
|---|---|
| Mises à jour | 68 paquets mis à jour, redémarrage sur le noyau 7.0.0-44 |
| Mises à jour de sécurité automatiques | `unattended-upgrades` actif (il l'était déjà) |
| SSH | clé uniquement : `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no` |
| Pare-feu `ufw` | actif : tout refuser en entrée sauf SSH (22) |

**Piège rencontré sur SSH.** `50-cloud-init.conf` réactivait la connexion par mot de passe, parce que sshd retient **la première valeur lue**, fichiers pris dans l'ordre alphabétique. Le durcissement est donc dans `/etc/ssh/sshd_config.d/00-durcissement.conf`, lu en premier. Pour vérifier la valeur réellement appliquée :
```bash
sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication)'   # tout à « no »
```
Méthode suivie pour ne pas se fermer l'accès :
- programmer un retour arrière automatique avec `systemd-run --on-active=180` ;
- appliquer la modification ;
- tester une **nouvelle** connexion par clé ;
- annuler le retour arrière seulement si cette connexion a réussi.

**ufw et Docker.** ufw protège tout ce qui n'est pas publié par Docker. Le port 443 du relais est publié par Docker, qui contourne ufw : il sera joignable sans règle ufw, et c'est nginx qui le filtre (adresses Cloudflare seulement).

---

## Étape 4 : installer Beyassa ✅ fait le 22/11/2026

Installé dans `~/beyassa` (utilisateur `christian`). Les secrets du `.env` ont été générés sur le serveur et n'en sont jamais sortis. Le certificat d'origine (`*.beyassa.org`, valable jusqu'en 2041) a été vérifié avant la copie : émis par Cloudflare et cohérent avec sa clé. Vérifications faites à travers Cloudflare : page d'accueil, QR code, connexion admin, export, IP réelle dans les journaux, refus de l'IP directe et de toute connexion hors Cloudflare (444), aucune trace du jeton dans les journaux, première sauvegarde. Tâche mensuelle de mise à jour des adresses Cloudflare installée (`crontab -l`).

**Mot de passe administrateur initial** : il a été généré au hasard. Pour le lire : `ssh vps-elyon-staging "grep ADMIN_MOT_DE_PASSE ~/beyassa/.env"`. Le changer dès la première connexion. La valeur du `.env` ne sert qu'à créer le compte au tout premier démarrage.

Commandes de référence, pour une réinstallation :

```bash
ssh vps-elyon-staging
git clone https://github.com/yalatif0210/these_beyassa.git ~/beyassa
cd ~/beyassa
cp .env.example .env
chmod 600 .env
openssl rand -hex 32        # à coller dans SECRET_KEY
openssl rand -hex 24        # à coller dans POSTGRES_PASSWORD (hexadécimal : « / » et « + » casseraient l'adresse de la base)
nano .env                   # remplir SECRET_KEY, ADMIN_MOT_DE_PASSE, POSTGRES_PASSWORD ; DOMAINE et BASE_URL valent déjà etude.beyassa.org
mkdir -p deploy/certs && chmod 700 deploy/certs
exit
```
Depuis le PC, dans le dossier où sont `origine.pem` et `origine.key` :
```bash
scp origine.pem origine.key vps-elyon-staging:beyassa/deploy/certs/
ssh vps-elyon-staging 'chmod 600 ~/beyassa/deploy/certs/*'
```
Puis démarrer :
```bash
ssh vps-elyon-staging
cd ~/beyassa
docker compose up -d --build --wait
docker compose ps           # db, web et relais « healthy », sauvegarde « Up »
```
L'application refuse de démarrer si une valeur d'exemple (`a_remplacer`) est restée dans `.env`.

**Vérifier depuis le PC :**
```bash
curl -sI https://etude.beyassa.org/bienvenue | head -1                  # HTTP/2 200
curl -sk --max-time 10 https://169.58.210.138/ ; echo "code $?"          # code 35 : l'accès direct à l'IP est refusé
```

**Mise en service** : voir la section « Mise en service » du README (changer le mot de passe admin, ajouter les chirurgiens, régler les paramètres, imprimer le QR code).

---

## Exploitation

**Mettre à jour l'application**
```bash
cd ~/beyassa && git pull && docker compose up -d --build --wait
```
Il n'y a pas de migrations : un changement de colonne demande une intervention manuelle (voir CLAUDE.md).

**Journaux**
```bash
docker compose logs -f web relais
```
Ils sont limités à 5 fichiers de 10 Mo par service.

**Liste des adresses Cloudflare** : à rafraîchir chaque mois par une tâche planifiée. Pour cela, lancer `crontab -e` et ajouter :
```
0 4 1 * * cd $HOME/beyassa && sh deploy/maj_ips_cloudflare.sh >> $HOME/maj_ips_cloudflare.log 2>&1
```
Le script ne touche à rien si la liste reçue est anormale, et revient à l'ancienne liste si nginx refuse la nouvelle.

**Sauvegardes** : une par jour dans `~/beyassa/sauvegardes`, conservées 30 jours. Elles sont **sur le même disque que la base** : une panne du serveur emporterait les deux. Il faut donc les rapatrier régulièrement sur un support chiffré, au moins une fois par semaine. Depuis le PC :
```bash
scp "vps-elyon-staging:beyassa/sauvegardes/beyassa_*.sql.gz" D:/sauvegardes_beyassa/
```

**Restaurer une sauvegarde**
```bash
gunzip -c sauvegardes/beyassa_AAAAMMJJ_HHMM.sql.gz | docker compose exec -T db psql -U beyassa -d beyassa
```

**Erreurs Cloudflare fréquentes**

| Erreur | Cause probable |
|---|---|
| 521 | Le relais ne tourne pas : `docker compose ps`, puis `docker compose up -d`. |
| 525 / 526 | Certificat d'origine absent, mal copié ou pour un autre nom : vérifier `deploy/certs/` et le mode « Complet (strict) ». |
| 522 | Le port 443 est injoignable : un autre service l'occupe, ou le pare-feu de l'hébergeur le bloque. |
| Page blanche après connexion | Rocket Loader est activé : le désactiver. |

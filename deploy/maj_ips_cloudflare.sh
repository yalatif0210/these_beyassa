#!/bin/sh
# Met à jour la liste des adresses de Cloudflare utilisée par le relais nginx, puis le recharge.
# Cloudflare change rarement ses adresses : lancer ce script une fois par mois suffit
# (voir deploy/DEPLOIEMENT_VPS.md, tâche cron). À lancer depuis le dossier du projet sur le serveur.
set -eu

dossier="$(cd "$(dirname "$0")" && pwd)/nginx/cloudflare"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsS --max-time 30 https://www.cloudflare.com/ips-v4 > "$tmp/v4"
curl -fsS --max-time 30 https://www.cloudflare.com/ips-v6 > "$tmp/v6"
cat "$tmp/v4" "$tmp/v6" | tr -d '\r' | grep -v '^$' > "$tmp/plages"

# Garde-fou : uniquement des plages d'adresses, et une liste plausible. Sinon on ne touche à rien,
# car une liste vide ou fausse couperait l'accès à l'application.
if grep -qvE '^[0-9a-fA-F:.]+/[0-9]{1,3}$' "$tmp/plages" || [ "$(wc -l < "$tmp/plages")" -lt 10 ]; then
    echo "Liste reçue inattendue : rien n'est modifié." >&2
    exit 1
fi

entete="# Généré par deploy/maj_ips_cloudflare.sh le $(date +%Y-%m-%d) (source : www.cloudflare.com/ips-v4 et ips-v6)"
{ echo "$entete"; sed 's/.*/set_real_ip_from &;/' "$tmp/plages"; } > "$tmp/realip.conf"
{ echo "$entete"; sed 's/.*/& 1;/' "$tmp/plages"; } > "$tmp/geo.conf"

# Comparaison sans la première ligne (l'en-tête est daté).
if [ "$(tail -n +2 "$tmp/geo.conf")" = "$(tail -n +2 "$dossier/geo.conf" 2>/dev/null)" ]; then
    echo "Liste Cloudflare inchangée."
    exit 0
fi

cp "$dossier/realip.conf" "$tmp/realip.conf.ancien"
cp "$dossier/geo.conf" "$tmp/geo.conf.ancien"
cp "$tmp/realip.conf" "$dossier/realip.conf"
cp "$tmp/geo.conf" "$dossier/geo.conf"

cd "$dossier/../../.."
if docker compose exec -T relais nginx -t; then
    docker compose exec -T relais nginx -s reload
    echo "Liste Cloudflare mise à jour et relais rechargé."
else
    # Configuration refusée : on remet l'ancienne liste.
    cp "$tmp/realip.conf.ancien" "$dossier/realip.conf"
    cp "$tmp/geo.conf.ancien" "$dossier/geo.conf"
    echo "Nouvelle liste refusée par nginx : ancienne liste remise." >&2
    exit 1
fi

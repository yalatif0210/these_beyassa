#!/bin/sh
# Sauvegarde quotidienne de la base, conservée CONSERVATION_JOURS jours.
set -eu
mkdir -p /sauvegardes
while true; do
  fichier="/sauvegardes/beyassa_$(date +%Y%m%d_%H%M).sql.gz"
  if pg_dump --no-owner | gzip > "$fichier"; then
    echo "Sauvegarde OK : $fichier"
  else
    echo "ÉCHEC de la sauvegarde" >&2
    rm -f "$fichier"
  fi
  find /sauvegardes -name 'beyassa_*.sql.gz' -mtime +"${CONSERVATION_JOURS:-30}" -delete
  sleep 86400
done

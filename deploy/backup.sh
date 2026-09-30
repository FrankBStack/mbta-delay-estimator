#!/bin/bash
# Nightly: dump what can't be rebuilt and copy it off the box.
#
# arrival_score_daily is kept for good and is the only table nothing can
# regenerate. arrival_score is kept 60 days but built from 48 hours of
# positions, so each night takes the last two days of it; the overlap covers a
# missed night. With BACKUP_URL set to a bucket's pre-authenticated request URL
# (Oracle Object Storage, ending in /o/), each file is PUT there too.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
DATE=$(date -u +%F)
DB="docker compose exec -T db"
mkdir -p backups

$DB pg_dump -U tracker -d tracker --data-only -t arrival_score_daily \
    | gzip > "backups/rollup-$DATE.sql.gz"
$DB psql -U tracker -d tracker -Atc "\copy (SELECT * FROM arrival_score
    WHERE arrived_at > now() - interval '2 days') TO STDOUT WITH CSV HEADER" \
    | gzip > "backups/arrivals-$DATE.csv.gz"
find backups -name '*.gz' -mtime +14 -delete

if [ -n "${BACKUP_URL:-}" ]; then
    for f in "backups/rollup-$DATE.sql.gz" "backups/arrivals-$DATE.csv.gz"; do
        curl -sfS -T "$f" "$BACKUP_URL$(basename "$f")" && echo "uploaded $f" \
            || echo "upload failed: $f"
    done
else
    echo "BACKUP_URL unset: dumps stay on this disk"
fi
echo "== $(date -u +%T) $(du -sh backups | cut -f1) in backups"

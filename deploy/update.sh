#!/bin/bash
# Deploy main on the box: pull, build, restart. Run it detached and poll the
# log; ssh sessions that go quiet for a minute get interrupted:
#   nohup bash -c './deploy/update.sh; echo EXIT=$?' >> update.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
P="docker compose exec -T db psql -U tracker -d tracker -Atc"
echo "== $(date -u +%T) pull";  git pull --ff-only || exit 1
# --pull so the base images pick up their security updates
echo "== $(date -u +%T) build"; docker compose build --pull 2>&1 | tail -3 || exit 1
# a scoring pass mid-flight would hold the restart's schema check off its
# locks; the poller redoes the pass next hour. This also kills a manual
# `scoring --hours N`, so don't deploy while one is running
pid=$($P "SELECT pid FROM pg_stat_activity WHERE datname = 'tracker' AND state = 'active' AND query LIKE '%WITH arrivals%' AND pid <> pg_backend_pid()")
if [ -n "$pid" ]; then echo "== cancelling scoring pass $pid: $($P "SELECT pg_cancel_backend($pid)")"; sleep 3; fi
echo "== $(date -u +%T) up";    docker compose up -d 2>&1 | tail -4 || exit 1
echo "== $(date -u +%T) prune"; docker builder prune -f 2>&1 | tail -1
echo "== $(date -u +%T) done"

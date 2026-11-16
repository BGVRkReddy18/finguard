#!/usr/bin/env bash
# Runs once under supervisord after the infrastructure processes start.
set -euo pipefail
wait_for() {
  local name=$1; shift
  for _ in $(seq 1 180); do "$@" >/dev/null 2>&1 && { echo "[init] $name ready"; return; }; sleep 1; done
  echo "[init] $name did not start"; exit 1
}
wait_for postgres pg_isready -h 127.0.0.1 -U finguard -d postgres
wait_for redis redis-cli -h 127.0.0.1 ping
wait_for kafka kafka-broker-api-versions.sh --bootstrap-server 127.0.0.1:9092

createdb -h 127.0.0.1 -U finguard finguard
cd /srv/backend
python manage.py migrate --noinput -v 0
python manage.py seed_demo_users
for t in transactions.raw transactions.scored cases.opened; do
  kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --create --if-not-exists --topic "$t" --partitions 3 --replication-factor 1 >/dev/null
done
echo "[init] database + topics ready"

PYTHONPATH=/srv/ml_service:/srv/simulator python /srv/hf/warm_features.py
supervisorctl -c /srv/hf/supervisord.conf start apps:*
echo "[init] FinGuard is up"

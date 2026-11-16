#!/usr/bin/env bash
# Boot: fresh demo state every start (Spaces' free disk is ephemeral anyway), random internal secrets,
# then hand over to supervisord, which runs infra first and starts the apps once init.sh succeeds.
set -euo pipefail
export DATA_DIR="${DATA_DIR:-$HOME/data}"
rm -rf "$DATA_DIR" && mkdir -p "$DATA_DIR"/{pg,kafka}
rand() { python -c "import secrets; print(secrets.token_urlsafe($1))"; }

export SPACE_HOST="${SPACE_HOST:-localhost:7860}"     # set by Hugging Face to <user>-<space>.hf.space
HOST="${SPACE_HOST%%:*}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-$(rand 48)}" DJANGO_DEBUG=false
export DJANGO_ALLOWED_HOSTS="$HOST,localhost,127.0.0.1"
export CSRF_TRUSTED_ORIGINS="https://$SPACE_HOST,http://$SPACE_HOST" CORS_ALLOWED_ORIGINS="https://$SPACE_HOST"
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 POSTGRES_DB=finguard POSTGRES_USER=finguard
export POSTGRES_PASSWORD="$(rand 24)" READONLY_DB_PASSWORD="$(rand 24)" AI_SERVICE_TOKEN="$(rand 32)"
export PGPASSWORD="$POSTGRES_PASSWORD" PGDATA="$DATA_DIR/pg"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(rand 18)}" DEMO_USER_PASSWORD=finguard123
export DATABASE_URL="postgresql://finguard_ro:${READONLY_DB_PASSWORD}@127.0.0.1:5432/finguard"
export REDIS_URL=redis://127.0.0.1:6379/0 KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
export BACKEND_URL=http://127.0.0.1:8000 JWT_SECRET="$DJANGO_SECRET_KEY" CORS_ORIGINS="https://$SPACE_HOST"
# Match the traffic rate the model was trained on (5 tx/s): measured precision drops 0.79 -> 0.72 at 3 tx/s
export SCORER=auto TPS="${SIM_TPS:-5}" NUM_CUSTOMERS=5000 FRAUD_RATE=0.01
export AUTO_INVESTIGATE_DAILY_TOKENS="${AUTO_INVESTIGATE_DAILY_TOKENS:-60000}"
export USER_ASK_PER_HOUR="${USER_ASK_PER_HOUR:-15}" USER_INVESTIGATE_PER_HOUR="${USER_INVESTIGATE_PER_HOUR:-15}"

# Postgres cluster (superuser "finguard", password auth even on localhost)
PGBIN="$(ls -d /usr/lib/postgresql/*/bin | head -1)"; export PGBIN
printf '%s' "$POSTGRES_PASSWORD" > /tmp/pgpw
"$PGBIN/initdb" -D "$PGDATA" -U finguard --pwfile=/tmp/pgpw --auth=scram-sha-256 -E UTF8 >/dev/null
rm -f /tmp/pgpw

# Kafka (single-node KRaft)
sed "s#__LOG_DIR__#$DATA_DIR/kafka#" /srv/hf/kafka.properties > /tmp/kafka.properties
kafka-storage.sh format -t "$(kafka-storage.sh random-uuid)" -c /tmp/kafka.properties >/dev/null

echo "FinGuard booting on https://$SPACE_HOST (admin password is in ADMIN_PASSWORD secret, or random)"
exec supervisord -c /srv/hf/supervisord.conf

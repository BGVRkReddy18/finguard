#!/usr/bin/env bash
# Render runs this on every start: apply migrations (idempotent), ensure demo users, serve.
set -euo pipefail
cd /srv/backend
python manage.py migrate --noinput -v 1
python manage.py seed_demo_users
cd /srv/lite
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips '*' \
     --ws-ping-interval 20 --log-level warning

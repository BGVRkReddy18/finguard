#!/usr/bin/env bash
# Create .env.prod with strong random secrets.   Usage: ./deploy/gen-env.sh <domain>
# Free HTTPS domain without buying one: <public-ip>.sslip.io  (e.g. 140.238.1.2.sslip.io)
set -euo pipefail
DOMAIN="${1:?usage: $0 <domain>   e.g. 140.238.1.2.sslip.io}"
OUT="${2:-.env.prod}"
[[ -e "$OUT" ]] && { echo "$OUT already exists — refusing to overwrite secrets"; exit 1; }
rand() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "${1:-40}"; }

ADMIN_PASSWORD="$(rand 20)"
GRAFANA_ADMIN_PASSWORD="$(rand 20)"
umask 077   # secrets file readable by the owner only
cat > "$OUT" <<ENV
DOMAIN=$DOMAIN
DJANGO_SECRET_KEY=$(rand 50)
POSTGRES_PASSWORD=$(rand 32)
READONLY_DB_PASSWORD=$(rand 32)
AI_SERVICE_TOKEN=$(rand 40)
ADMIN_PASSWORD=$ADMIN_PASSWORD
GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD
# Public demo accounts (analyst / manager) — shown on the login page
DEMO_USER_PASSWORD=finguard123

# Paste your free Groq key (https://console.groq.com/keys). Empty = offline template mode.
LLM_API_KEY=
SIM_TPS=5
ENV
echo "Wrote $OUT for https://$DOMAIN"
echo "  Django admin : admin / $ADMIN_PASSWORD"
echo "  Grafana      : admin / $GRAFANA_ADMIN_PASSWORD   (https://$DOMAIN/grafana)"
echo "Save these now — they are only in $OUT. Next: add LLM_API_KEY to $OUT."

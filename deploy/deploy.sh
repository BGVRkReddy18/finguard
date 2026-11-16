#!/usr/bin/env bash
# Build and (re)start the production stack. Safe to re-run; used by the GitHub Actions deploy job.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f "${ENV_FILE:-.env.prod}" ]] || { echo "${ENV_FILE:-.env.prod} missing — run ./deploy/gen-env.sh <domain> first"; exit 1; }
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file $ENV_FILE"

git pull --ff-only
$COMPOSE build --pull
$COMPOSE up -d --remove-orphans
docker image prune -f >/dev/null
$COMPOSE ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

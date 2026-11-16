#!/usr/bin/env bash
# One-time: warm the Redis feature store with 24 h of simulated history so customers aren't cold-start.
# Uses the committed model (no retraining in production).
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file $ENV_FILE"
mkdir -p data
$COMPOSE stop simulator ml-service
$COMPOSE run --rm --no-deps -v "$PWD/data:/data" simulator python generate_history.py --hours 24 --tps 5 --out /data/history.csv.gz
$COMPOSE --profile tools run --rm trainer python -m training.backfill --data /data/history.csv.gz
$COMPOSE up -d ml-service simulator
echo "Feature store warmed."

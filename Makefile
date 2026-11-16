.PHONY: up down logs ps test test-backend test-ml test-ai test-frontend shell reset dataset train backfill ml-bootstrap mlflow evaluate monitoring

up:            ## Build and start the whole stack
	docker compose up --build -d

down:          ## Stop everything
	docker compose down

reset:         ## Stop everything and wipe the database
	docker compose down -v

logs:          ## Follow logs of the pipeline services
	docker compose logs -f ml-service ingest-worker simulator

ps:
	docker compose ps

test: test-backend test-ml test-ai test-frontend

test-backend:
	docker compose run --rm --no-deps -e POSTGRES_HOST= backend pytest -q

test-ml:
	docker compose run --rm --no-deps -e KAFKA_ENABLED=false ml-service pytest -q

test-ai:
	docker compose run --rm --no-deps -e KAFKA_ENABLED=false ai-service pytest -q

test-frontend:  ## Type-check, lint and production-build the frontend
	cd frontend && npm ci && npx tsc --noEmit && npm run lint && npm run build

shell:
	docker compose exec backend python manage.py shell

# ---------- Machine learning ----------
dataset:       ## Generate 24h of labelled history (simulated clock)
	docker compose run --rm --no-deps simulator python generate_history.py --hours 24 --out /data/history.csv.gz

train:         ## Train XGBoost + benchmark against rules (logs to MLflow)
	docker compose --profile tools run --rm trainer python -m training.train

backfill:      ## Load customer profiles from history into Redis
	docker compose --profile tools run --rm trainer python -m training.backfill

ml-bootstrap:  ## Full ML setup: pause stream -> dataset -> train -> backfill -> resume
	docker compose stop simulator ml-service
	$(MAKE) dataset train backfill
	docker compose up -d ml-service simulator

mlflow:        ## MLflow UI on http://localhost:5050
	docker compose --profile tools up -d mlflow

evaluate:      ## Live precision/recall per model version (from ground-truth labels)
	docker compose exec backend python manage.py evaluate_live

monitoring:    ## Prometheus on :9090, Grafana on :3001 (dashboard "FinGuard — Operations")
	docker compose --profile monitoring up -d prometheus grafana

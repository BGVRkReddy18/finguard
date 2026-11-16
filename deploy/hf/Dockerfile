# FinGuard all-in-one image for Hugging Face Spaces (free CPU: 2 vCPU / 16 GB, one container, port 7860).
# The multi-service production stack is docker-compose.prod.yml; this image runs the same services
# under supervisord, with Postgres, Redis and Kafka inside the container.

# ---- frontend build (same-origin URLs, so the image works on any domain) ----
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_PUBLIC_API_URL="" NEXT_PUBLIC_AI_URL=/ai NEXT_PUBLIC_ML_URL=/ml \
    NEXT_PUBLIC_DEMO_ACCOUNTS=analyst,manager NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM caddy:2.8.4 AS caddy
# Kafka distribution from the official image (pure Java — runs on the JRE below). Docker Hub is far
# faster and more reliable than archive.apache.org downloads.
FROM apache/kafka:3.8.0 AS kafka

# ---- runtime ----
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql postgresql-client redis-server \
      openjdk-17-jre-headless libstdc++6 curl ca-certificates procps \
 && rm -rf /var/lib/apt/lists/*

COPY --from=kafka /opt/kafka /opt/kafka
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
COPY --from=web /usr/local/bin/node /usr/local/bin/node

COPY backend/requirements.txt /tmp/req/backend.txt
COPY ml_service/requirements.txt /tmp/req/ml.txt
COPY ai_service/requirements.txt /tmp/req/ai.txt
# supervisor 4.2.x imports pkg_resources (setuptools), which python:3.12 images no longer ship
RUN pip install --no-cache-dir supervisor==4.2.5 "setuptools==75.6.0" -r /tmp/req/backend.txt -r /tmp/req/ml.txt -r /tmp/req/ai.txt

RUN useradd -m -u 1000 user   # Spaces run containers as uid 1000
COPY --chown=user backend /srv/backend
COPY --chown=user ml_service /srv/ml_service
COPY --chown=user ai_service /srv/ai_service
COPY --chown=user simulator /srv/simulator
COPY --from=web --chown=user /web/.next/standalone /srv/frontend
COPY --from=web --chown=user /web/.next/static /srv/frontend/.next/static
COPY --from=web --chown=user /web/public /srv/frontend/public
COPY --chown=user deploy/hf /srv/hf
RUN cd /srv/backend && DJANGO_DEBUG=true python manage.py collectstatic --noinput -v 0 \
 && chmod +x /srv/hf/*.sh

USER user
ENV HOME=/home/user PATH=/opt/kafka/bin:/home/user/.local/bin:$PATH
EXPOSE 7860
CMD ["/srv/hf/entrypoint.sh"]

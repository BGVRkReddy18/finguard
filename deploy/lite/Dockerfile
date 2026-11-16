# FinGuard Cloud Lite — one process for free hosting (Render free web service + Neon Postgres).
# Same application code as the full stack; see deploy/lite/server.py for what is swapped.
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FINGUARD_ROOT=/srv

COPY backend/requirements.txt /tmp/req/backend.txt
COPY ml_service/requirements.txt /tmp/req/ml.txt
COPY ai_service/requirements.txt /tmp/req/ai.txt
# xgboost-cpu: same library without the ~200 MB CUDA/NCCL payload; test tools are not needed at runtime
RUN sed -i 's/^xgboost==/xgboost-cpu==/' /tmp/req/ml.txt \
 && cat /tmp/req/*.txt | grep -vE '^(pytest|pytest-django|pytest-asyncio|fakeredis|gunicorn|confluent-kafka)' > /tmp/req/all.txt \
 && pip install --no-cache-dir -r /tmp/req/all.txt "confluent-kafka==2.6.1"

RUN useradd -m -u 1000 app
COPY --chown=app backend /srv/backend
COPY --chown=app ml_service/app /srv/lite/mlapp
COPY --chown=app ml_service/artifacts /srv/lite/artifacts
COPY --chown=app ai_service/app /srv/lite/aiapp
COPY --chown=app simulator/generator.py /srv/simulator/generator.py
COPY --chown=app deploy/lite/server.py deploy/lite/start.sh /srv/lite/
RUN cd /srv/backend && DJANGO_DEBUG=true python manage.py collectstatic --noinput -v 0 && chmod +x /srv/lite/start.sh

USER app
EXPOSE 10000
CMD ["/srv/lite/start.sh"]

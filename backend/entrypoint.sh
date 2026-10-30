#!/bin/sh
set -eu
case "$1" in
  api)
    alembic upgrade head
    if [ "${SEED_DEMO:-0}" = "1" ]; then
      python -m resolveflow.seed --if-empty
    fi
    exec uvicorn resolveflow.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec celery -A resolveflow.celery_app worker --loglevel=INFO
    ;;
  beat)
    exec celery -A resolveflow.celery_app beat --loglevel=INFO -s /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac

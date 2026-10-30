#!/bin/sh
set -eu
case "$1" in
  api)
    alembic upgrade head
    exec uvicorn resolveflow.main:app --host 0.0.0.0 --port 8000
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

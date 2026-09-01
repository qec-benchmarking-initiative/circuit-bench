#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail

python manage.py migrate --noinput
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --access-logfile -

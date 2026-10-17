#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py ensure_bucket --retries 10 --delay 3
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2 --access-logfile -

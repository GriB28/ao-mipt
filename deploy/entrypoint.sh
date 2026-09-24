#!/bin/sh
# Точка входа контейнера сайта. Один образ — несколько ролей:
#
#   web      миграции + gunicorn (основной процесс сайта)
#   mailer   раз в минуту отправляет порцию писем из очереди рассылок
#   <любая команда>  выполняется как есть, например:
#            docker compose run --rm web python manage.py createsuperuser
set -e

case "$1" in
  web)
    python manage.py migrate --noinput
    exec gunicorn config.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --graceful-timeout 30 \
      --max-requests 1000 --max-requests-jitter 100 \
      --access-logfile - \
      --forwarded-allow-ips "*"
    ;;
  mailer)
    echo "Рассылки: проверяю очередь раз в минуту"
    while true; do
      python manage.py send_newsletters || echo "send_newsletters упал, повторю через минуту"
      sleep 60
    done
    ;;
  *)
    exec "$@"
    ;;
esac

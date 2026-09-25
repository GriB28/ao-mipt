#!/bin/sh
# Первый выпуск сертификата Let's Encrypt. Запускать один раз, когда:
#   1) DNS-запись домена уже указывает на этот сервер;
#   2) в .env заполнены DOMAIN и LETSENCRYPT_EMAIL;
#   3) сайт поднят (`docker compose up -d`) и открывается по http://DOMAIN.
# Дальше сертификат продлевает контейнер certbot сам.
set -eu
cd "$(dirname "$0")/.."

env_value() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '"'"'"; }
DOMAIN=$(env_value DOMAIN)
EMAIL=$(env_value LETSENCRYPT_EMAIL)

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Заполните DOMAIN и LETSENCRYPT_EMAIL в .env" >&2
    exit 1
fi

echo "Выпускаю сертификат для $DOMAIN…"
docker compose run --rm --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$DOMAIN" --email "$EMAIL" \
    --agree-tos --no-eff-email --non-interactive

echo "Перезапускаю nginx, он переключится на https…"
docker compose restart nginx
echo "Готово: https://$DOMAIN"

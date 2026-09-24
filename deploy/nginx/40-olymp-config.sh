#!/bin/sh
# Запускается официальным образом nginx перед стартом (/docker-entrypoint.d/).
# Выбирает конфигурацию: https, если сертификат для DOMAIN уже выпущен,
# иначе http — чтобы сайт поднялся и Let's Encrypt смог его проверить.
set -e

CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
export CLIENT_MAX_BODY_SIZE="${CLIENT_MAX_BODY_SIZE:-100m}"

if [ -n "$DOMAIN" ] && [ -f "$CERT" ]; then
    template=https
else
    template=http
    [ -n "$DOMAIN" ] && echo "olymp: сертификата для $DOMAIN пока нет — работаю по http. См. docs/deploy.md, шаг «HTTPS»."
fi

# Подставляем только свои переменные: $host, $request_uri и прочие
# переменные nginx должны остаться как есть.
envsubst '${DOMAIN} ${CLIENT_MAX_BODY_SIZE}' \
    < "/etc/nginx/olymp/${template}.conf.template" \
    > /etc/nginx/conf.d/default.conf
echo "olymp: конфигурация nginx — ${template}"

# Certbot продлевает сертификат сам, но nginx держит старый в памяти,
# пока его не перезагрузить. Раз в шесть часов перечитываем.
if [ "$template" = https ]; then
    (while sleep 6h; do nginx -s reload; done) &
fi

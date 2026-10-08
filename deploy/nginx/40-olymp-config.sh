#!/bin/sh
# Запускается официальным образом nginx перед стартом (/docker-entrypoint.d/).
set -e

export CLIENT_MAX_BODY_SIZE="${CLIENT_MAX_BODY_SIZE:-100m}"

# Подставляем только свои переменные: $host, $request_uri и прочие
# переменные nginx должны остаться как есть.
envsubst '${CLIENT_MAX_BODY_SIZE}' \
    < /etc/nginx/olymp/http.conf.template \
    > /etc/nginx/conf.d/default.conf
echo "olymp: конфигурация nginx сформирована"

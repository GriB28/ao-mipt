#!/bin/sh
# Подготовка чистого сервера (Ubuntu 22.04/24.04 или Debian 12) под сайт.
# Запускать от root:
#
#   curl -fsSL https://raw.githubusercontent.com/leeiozh/ao-mipt/main/deploy/server-setup.sh | sh
#   # или, если репозиторий уже склонирован:
#   sh deploy/server-setup.sh
#
# Что делает (повторный запуск безопасен):
#   - ставит Docker из официального репозитория, git и фаервол ufw;
#   - открывает наружу только ssh, 80 и 443;
#   - клонирует репозиторий в /srv/olymp;
#   - создаёт .env со случайными SECRET_KEY и паролем базы.
# Дальше — заполнить домен и почту в .env и выполнить шаги из docs/deploy.md.
set -eu

REPO="${REPO:-https://github.com/leeiozh/ao-mipt.git}"
DIR="${DIR:-/srv/olymp}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Нужен root: sudo sh $0" >&2
    exit 1
fi

echo "== Пакеты"
apt-get update -q
apt-get install -y -q ca-certificates curl git ufw openssl

if ! command -v docker >/dev/null 2>&1; then
    echo "== Docker"
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "== Фаервол: ssh, http, https"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

if [ ! -d "$DIR/.git" ]; then
    echo "== Код в $DIR"
    git clone "$REPO" "$DIR"
fi
cd "$DIR"

if [ ! -f .env ]; then
    echo "== .env со случайными секретами"
    secret=$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-50)
    dbpass=$(openssl rand -hex 24)
    sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$secret|" \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$dbpass|" \
        .env.example > .env
    chmod 600 .env
fi

cat <<MSG

Сервер готов. Дальше:
  1. nano $DIR/.env — впишите DOMAIN, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS,
     LETSENCRYPT_EMAIL и почту (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD).
  2. cd $DIR && docker compose up -d --build
  3. sh deploy/https-init.sh
  4. docker compose exec web python manage.py createsuperuser
Подробно — docs/deploy.md.
MSG

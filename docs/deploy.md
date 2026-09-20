# Развёртывание и эксплуатация

## Что нужно купить

| Что | Где | Цена ориентировочно |
|---|---|---|
| VPS 2 vCPU / 4 ГБ / 40 ГБ | Timeweb Cloud, Selectel, reg.ru, Beget | 500–900 ₽/мес |
| Домен `.ru` | reg.ru, nic.ru | 200–1000 ₽/год |
| TLS-сертификат | Let's Encrypt | бесплатно |
| SMTP для писем | Яндекс 360, Unisender, SendPulse | от 0 ₽ |

Такой конфигурации хватает на несколько тысяч участников. Если МФТИ выделит
свою виртуалку — всё переносится без изменений, стек в контейнерах.

## Первая установка на сервер

```bash
# на сервере, под пользователем с sudo
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER   # перелогиниться

git clone <адрес репозитория> /srv/olymp
cd /srv/olymp

cp .env.example .env
nano .env     # заполнить SECRET_KEY, ALLOWED_HOSTS, POSTGRES_PASSWORD, SMTP

docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Сгенерировать `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

## HTTPS

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d olymp.example.ru
```

Затем в `deploy/nginx.conf` добавить блок `listen 443 ssl;` с путями к
сертификатам и смонтировать `/etc/letsencrypt` в контейнер nginx.
Обновление — по cron: `certbot renew --quiet && docker compose restart nginx`.

## Обновление кода

```bash
cd /srv/olymp
git pull
docker compose up -d --build
docker compose exec web python manage.py migrate
```

Позже это стоит вынести в GitHub Actions: пуш в `main` → сборка → деплой по SSH.

## Бэкапы — обязательно

Терять решения участников в день дедлайна нельзя. Ежедневно по cron:

```bash
# /etc/cron.daily/olymp-backup
#!/bin/sh
cd /srv/olymp
docker compose exec -T db pg_dump -U olymp olymp | gzip > /backup/db-$(date +%F).sql.gz
tar czf /backup/media-$(date +%F).tar.gz -C /var/lib/docker/volumes/olymp_media/_data .
find /backup -mtime +30 -delete
```

Копии выгружать во внешнее хранилище (Яндекс Object Storage, Selectel S3) —
бэкап на том же сервере не спасает от потери сервера.

**Раз в сезон проверяйте восстановление** на тестовой машине. Непроверенный
бэкап — это не бэкап.

## Мониторинг

* **Sentry** — ошибки на проде, бесплатного тарифа хватает.
* **UptimeRobot** — проверка доступности раз в 5 минут, уведомления в Telegram.
* `docker compose logs -f web` — оперативный просмотр логов.

## Чек-лист перед запуском регистрации

- [ ] `DEBUG=False`, `ALLOWED_HOSTS` заполнен реальным доменом
- [ ] `SECRET_KEY` — случайный, не из примера
- [ ] HTTPS работает, http редиректит на https
- [ ] Письма реально доходят (проверить на Gmail, Яндекс и Mail.ru)
- [ ] Бэкап отработал хотя бы раз и восстанавливается
- [ ] Загрузка файла на 20 МБ проходит, на 100 МБ — даёт понятную ошибку
- [ ] Опубликована политика обработки персональных данных
- [ ] Создан администратор и заведены учётки организаторов
- [ ] Sentry и UptimeRobot подключены

## Пиковая нагрузка

Пик предсказуем — последние часы перед дедлайном. За день до него:

* проверить свободное место на диске (`df -h`) — загрузки съедают его быстро;
* поднять число gunicorn-воркеров (`--workers 5`);
* не выкатывать код в день дедлайна.

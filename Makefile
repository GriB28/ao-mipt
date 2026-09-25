# Короткие команды для повседневной работы.
# Запуск: make <цель>, например make dev

PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help start install dev migrations migrate seed superuser test lint fmt demo clean up down logs deploy https backup admin

help:  ## показать список команд
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

start:  ## всё сразу: зависимости, база, демо-данные, сервер
	@$(MAKE) install
	@$(MAKE) migrate
	@$(MAKE) seed
	@echo ""
	@echo "Готово. Сайт: http://127.0.0.1:8000"
	@echo "Вход: admin@example.ru / olymp12345"
	@echo "Остановить: Ctrl+C"
	@echo ""
	@$(MAKE) dev

install:  ## создать venv и поставить зависимости
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements-dev.txt
	@test -f .env || (sed 's/^DEBUG=False/DEBUG=True/' .env.example > .env && \
		echo "Создан .env для локальной работы (DEBUG=True)")

dev:  ## запустить сервер разработки на http://127.0.0.1:8000
	$(PY) manage.py runserver

migrations:  ## создать миграции после изменения моделей
	$(PY) manage.py makemigrations

migrate:  ## применить миграции к базе
	$(PY) manage.py migrate

seed:  ## наполнить базу демо-данными
	$(PY) manage.py seed_demo

superuser:  ## создать администратора
	$(PY) manage.py createsuperuser

test:  ## прогнать тесты
	$(PY) manage.py test

lint:  ## проверить стиль кода
	.venv/bin/ruff check .

fmt:  ## отформатировать код
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

demo:  ## собрать статическое демо в dist/ (показать коллегам)
	$(PY) manage.py export_static
	@echo "Откройте dist/index.html в браузере"

clean:  ## удалить локальную базу и медиа (осторожно)
	rm -f db.sqlite3
	rm -rf media/*

# --- Docker: сервер (подробно — docs/deploy.md) ---
up:  ## поднять всё в Docker (сборка + запуск)
	docker compose up -d --build

down:  ## остановить Docker
	docker compose down

logs:  ## смотреть логи сайта
	docker compose logs -f --tail=200 web

deploy:  ## обновить сервер: бэкап, подтянуть код, перезапустить
	@# Сначала бэкап: если обновление что-то сломает в базе, вернёмся к нему.
	@# Не получился бэкап — обновление не начинается.
	docker compose exec -T backup sh /backup.sh now
	git rev-parse --short HEAD > .last-deployed
	git pull --ff-only
	docker compose up -d --build
	docker compose ps
	@echo "Предыдущая версия: $$(cat .last-deployed). Откат — docs/deploy.md, «Если обновление сломало сайт»."

https:  ## выпустить сертификат Let's Encrypt (один раз)
	sh deploy/https-init.sh

backup:  ## сделать бэкап прямо сейчас (в ./backups)
	docker compose exec backup sh /backup.sh now

admin:  ## создать администратора на сервере
	docker compose exec web python manage.py createsuperuser

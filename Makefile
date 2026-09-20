# Короткие команды для повседневной работы.
# Запуск: make <цель>, например make dev

PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help install dev migrations migrate seed superuser test lint fmt clean up down logs

help:  ## показать список команд
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## создать venv и поставить зависимости
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements-dev.txt
	@test -f .env || (cp .env.example .env && echo "Создан .env — впишите DEBUG=True для локальной работы")

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

# --- Docker (для сервера и для тех, кому удобнее контейнеры) ---
up:  ## поднять всё в Docker
	docker compose up -d --build

down:  ## остановить Docker
	docker compose down

logs:  ## смотреть логи
	docker compose logs -f web

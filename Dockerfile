# Образ сайта: Django + gunicorn. Статику раздаёт сам Django через
# whitenoise (с кешированием навсегда), nginx только проксирует —
# поэтому отдельного тома под статику не нужно.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Зависимости отдельным слоем: при правке кода они не переустанавливаются.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Сайт работает не от root: если через загрузку файла что-то пойдёт
# не так, у процесса не будет прав на весь контейнер.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /app/staticfiles \
    && chown app:app /app/media /app/staticfiles

COPY --chown=app:app . .

# Статика собирается при сборке образа. Ключ здесь одноразовый: настоящий
# SECRET_KEY приходит из .env только при запуске контейнера.
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --noinput -v0

USER app

EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["web"]

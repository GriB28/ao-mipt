"""
Настройки проекта. Всё, что различается между машинами и серверами,
берётся из переменных окружения (файл .env), см. .env.example.
"""

import sys
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

# Под тестами не включаем прод-защиту: SSL-редирект ломает тестовый клиент.
TESTING = "test" in sys.argv
DEBUG = env("DEBUG")

# Ключ подписи сессий и токенов. В .env.example он пустой — чтобы никто
# случайно не выкатил на сервер ключ из репозитория. Поэтому:
#   локально — подставляем одноразовый, чтобы сайт просто запустился;
#   на сервере — падаем сразу, а не отдаём всем один и тот же ключ.
SECRET_KEY = env("SECRET_KEY", default="").strip()
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-insecure-key-not-for-production"
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY пуст, а DEBUG=False. Сгенерируйте ключ и впишите в .env:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

if DEBUG or TESTING:
    # Локально сайт всегда открывают с localhost, а в .env обычно лежат
    # боевые домены, скопированные из примера. Без этой добавки первый
    # же запрос упирается в «Invalid HTTP_HOST header».
    ALLOWED_HOSTS = list(dict.fromkeys(
        list(ALLOWED_HOSTS) + ["localhost", "127.0.0.1", "[::1]", "testserver"]
    ))

# --- Приложения -----------------------------------------------------------

DJANGO_APPS = [
    # 'whitenoise.runserver_nostatic',      # тестовый деплой: runserver при DEBUG=false
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.seasons",
    "apps.venues",
    "apps.participation",
    "apps.contest",
    "apps.content",
    "apps.mailing",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.seasons.context_processors.current_season",
                "apps.core.context_processors.site_settings",
            ],
        },
    },
]

# --- База данных ----------------------------------------------------------
# Локально по умолчанию SQLite (чтобы стартовать без Docker),
# на сервере — DATABASE_URL=postgres://user:pass@host:5432/dbname
#
# Пустую строку считаем «не задано»: в .env.example переменная объявлена
# без значения, и без этой проверки Django пытался бы подключиться к базе
# с пустым драйвером и падал на первой же команде.

_database_url = env("DATABASE_URL", default="").strip()
DATABASES = {
    "default": env.db_url_config(
        _database_url or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    )
}

# --- Пользователи ---------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailBackend"]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Локализация ----------------------------------------------------------

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# --- Статика и медиа ------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
# Тоже терпим пустое значение: пустой MEDIA_ROOT означал бы корень
# файловой системы, и загрузки полетели бы мимо проекта.
MEDIA_ROOT = env("MEDIA_ROOT", default="").strip() or str(BASE_DIR / "media")

# Решения участников закрыты от посторонних: их отдаёт представление
# contest:submission_file после проверки прав. На сервере сам файл
# передаёт nginx по X-Accel-Redirect — здесь указывается его internal-location
# (см. deploy/nginx.conf). Пусто — файл отдаёт Django (локальная работа).
PROTECTED_MEDIA_ACCEL_PREFIX = env("PROTECTED_MEDIA_ACCEL_PREFIX", default="").strip()

# В проде статика раздаётся whitenoise с хешами в именах файлов (кеш навсегда),
# но это требует collectstatic — поэтому локально и в тестах используем простой бэкенд.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Предел на файл для организаторов и администраторов (условия, данные
# к задачам, презентации лекций) — там бывают файлы по 8–10 МБ.
MAX_UPLOAD_SIZE_MB = env.int("MAX_UPLOAD_SIZE_MB", default=20)
# Предел на файл для школьников: решения и сканы согласий. Фото браузер
# сжимает сам перед отправкой, см. static/js/compress.js.
PARTICIPANT_UPLOAD_MAX_MB = env.float("PARTICIPANT_UPLOAD_MAX_MB", default=2)
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
# Сколько файлов в одной отправке и сколько отправок по одной задаче.
# Пределы защищают диск сервера; обычному участнику их не достичь.
MAX_FILES_PER_SUBMISSION = env.int("MAX_FILES_PER_SUBMISSION", default=10)
MAX_ATTEMPTS_PER_PROBLEM = env.int("MAX_ATTEMPTS_PER_PROBLEM", default=30)
MAX_CONSENT_UPLOADS = env.int("MAX_CONSENT_UPLOADS", default=10)
# /healthz/ отвечает 503, если места под загрузки осталось меньше.
HEALTHZ_MIN_FREE_GB = env.float("HEALTHZ_MIN_FREE_GB", default=2.0)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Почта ----------------------------------------------------------------
#
# Решает EMAIL_HOST, а не DEBUG: если в .env прописан SMTP-сервер, письма
# уходят по-настоящему — в том числе локально, чтобы можно было проверить,
# как выглядит письмо у живого получателя. Пусто — письма печатаются в тот
# терминал, где запущен runserver, и никуда не отправляются.
#
# Какой ящик заводить и где брать пароль приложения — docs/contacts.md.

EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = 10  # чтобы регистрация не висела, если SMTP не отвечает

if EMAIL_HOST and EMAIL_HOST_USER and EMAIL_HOST_PASSWORD and not (TESTING or DEBUG):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Обратный адрес. По умолчанию — сам почтовый ящик: Яндекс и большинство
# других SMTP отвергают письмо, если отправитель не совпадает с тем, под
# кем вошли. Отдельное значение нужно, только если провайдер разрешает
# отправку от имени другого адреса.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "olymp@example.ru")
# --- Публичные контакты и ссылки (показываются в подвале) ----------------

# Общие вопросы по олимпиаде.
CONTACT_EMAIL = env("CONTACT_EMAIL", default="olymp@example.ru")
# Технические вопросы по сайту: не работает загрузка, не приходит письмо.
SUPPORT_EMAIL = env("SUPPORT_EMAIL", default="")
# Телеграм-канал олимпиады.
TELEGRAM_URL = env("TELEGRAM_URL", default="")
# Телеграм-чат для участников (если отдельный от канала).
TELEGRAM_CHAT_URL = env("TELEGRAM_CHAT_URL", default="")
# Сообщество ВКонтакте — там же выкладываются лекции.
VK_URL = env("VK_URL", default="")
# Адрес сайта — называется в согласии на распространение ПД (где публикуются
# результаты). По умолчанию https://DOMAIN из той же настройки, что и для HTTPS.
SITE_URL = env("SITE_URL", default="").strip() or (
    f"https://{env('DOMAIN', default='').strip()}" if env("DOMAIN", default="").strip() else ""
)

# --- Карты ----------------------------------------------------------------
# Если ключ задан, карта площадок рисуется Яндекс.Картами.
# Без ключа используется OpenStreetMap — он работает без регистрации,
# но в некоторых сетях его тайлы недоступны.
YANDEX_MAPS_API_KEY = env("YANDEX_MAPS_API_KEY", default="")

# --- Безопасность (включается только в проде) -----------------------------

# USE_HTTPS=False нужен ровно в двух случаях: первый запуск на сервере,
# пока сертификат ещё не выпущен, и проверка Docker-сборки у себя на
# компьютере по http://localhost. Во всех остальных — True.
USE_HTTPS = env.bool("USE_HTTPS", default=True)

# За nginx: он сообщает, пришёл ли запрос по https.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG and not TESTING:
    X_FRAME_OPTIONS = "DENY"
    if USE_HTTPS:
        SECURE_SSL_REDIRECT = True
        # Проверка здоровья ходит в контейнер напрямую по http.
        SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# --- Логи -----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

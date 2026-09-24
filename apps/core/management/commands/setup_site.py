"""
Наполняет базу тем, что нужно настоящему сайту: сезон, этапы с датами,
тренировочная задача, служебные страницы, каталог лекций и фото финалов.

    python manage.py setup_site

Это команда для боевого сервера: никаких демо-пользователей, площадок и
решений она не создаёт (для этого — seed_demo). Повторный запуск безопасен:
она только добавляет недостающее и не трогает то, что уже поправили
в админке — даты этапов, тексты страниц, условия задач.
"""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.content.models import News, Page, Playlist
from apps.contest.models import Problem
from apps.core.legal_templates import (
    CONSENT_FORM_ADULT,
    CONSENT_FORM_MINOR,
    CONSENT_TEXT,
    PRIVACY_POLICY,
    RULES_TEXT,
)
from apps.seasons.models import Season, Stage
from apps.seasons.schedule import PRACTICE_STAGE, SEASON_YEAR, STAGES

PRACTICE_STATEMENT = (
    "<p>Это не настоящая задача олимпиады, а проверка связи: загрузите сюда "
    "любой файл — фото, PDF или текст — и нажмите «Отправить».</p>"
    "<p>Если после отправки на этой странице появилась карточка «Ваше последнее "
    "решение» с вашим файлом — всё работает, и во время тура решения будут "
    "доходить так же.</p>"
    "<p>Тренировочная задача открыта весь учебный год и на результаты не влияет. "
    "Отправить можно несколько раз.</p>"
)


class Command(BaseCommand):
    help = "Создаёт сезон, этапы, тренировочную задачу и служебные страницы (для сервера)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-dates", action="store_true",
            help="перезаписать даты этапов из apps/seasons/schedule.py "
                 "(правки дат в админке будут потеряны)",
        )

    def handle(self, *args, **options):
        season, _ = Season.objects.get_or_create(
            year=SEASON_YEAR,
            defaults={
                "slug": "ao27",
                "title": "Аэрокосмическая олимпиада МФТИ VII",
                "subtitle": "Сезон 2026/27",
                "accent_color": "#2f6fed",
                "is_active": True,
                "is_published": True,
            },
        )

        # Этапы берём из apps/seasons/schedule.py — там же лежат даты.
        # По умолчанию только добавляем недостающие: после запуска даты
        # правят в админке, и повторный запуск не должен их перетирать.
        stages = {}
        for plan in STAGES + [PRACTICE_STAGE]:
            plan = dict(plan)
            slug = plan.pop("slug")
            plan.setdefault("is_practice", False)
            method = (Stage.objects.update_or_create if options["update_dates"]
                      else Stage.objects.get_or_create)
            stages[slug], _ = method(season=season, slug=slug,
                                     defaults={**plan, "is_published": True})

        Problem.objects.get_or_create(
            stage=stages[PRACTICE_STAGE["slug"]], number=1,
            defaults={"title": "Тренировочная задача", "statement_html": PRACTICE_STATEMENT,
                      "max_score": None, "status": Problem.Status.APPROVED},
        )

        News.objects.get_or_create(
            slug="registration-open",
            defaults={
                "season": season,
                "title": "Открыта регистрация на АО VII",
                "summary": "Регистрируйтесь и выбирайте площадку очного этапа.",
                "body": "Регистрация участников открыта. Очный этап пройдёт 19–24 октября "
                        "на площадках в разных городах — выберите ближайшую на карте в "
                        "разделе «Очный тур» и запишитесь. Дистанционный этап начнётся "
                        "15 ноября. Участвовать можно в обоих форматах — засчитается "
                        "лучший результат.",
                "is_published": True,
            },
        )

        pages = [
            ("about", "Об олимпиаде", True, 10,
             "<p>Аэрокосмическая олимпиада МФТИ для школьников 7–11 классов.</p>"),
            ("rules", "Правила", True, 20, RULES_TEXT),
            ("privacy", "Политика обработки персональных данных", False, 90, PRIVACY_POLICY),
            ("consent", "Согласие на обработку персональных данных", False, 91, CONSENT_TEXT),
        ]
        for slug, title, in_menu, order, body in pages:
            Page.objects.get_or_create(
                slug=slug,
                defaults={"title": title, "show_in_menu": in_menu,
                          "menu_order": order, "body": body},
            )

        # Тексты бланков согласия (PDF в кабинете). Страницы не публикуются —
        # это заготовки с подстановками {{ … }}, их правят в админке.
        for slug, title, body in [
            ("consent-form-minor", "Бланк согласия: законный представитель", CONSENT_FORM_MINOR),
            ("consent-form-adult", "Бланк согласия: участник старше 18", CONSENT_FORM_ADULT),
        ]:
            Page.objects.get_or_create(
                slug=slug,
                defaults={"title": title, "body": body, "is_published": False,
                          "show_in_menu": False, "menu_order": 95},
            )

        # Каталог лекций прошлых лет — темы, лекции и плейлисты сезонов.
        call_command("seed_lectures", verbosity=0)

        # Плейлисты вне сезонной таблицы: курс по Python идёт вне сезонов.
        Playlist.objects.get_or_create(
            url="https://www.youtube.com/watch?v=vWDNxTdR690&list=PLncYbc2UAdLH3utmw0AKBDg08IXX8GdrP",
            defaults={"title": "Введение в Python",
                      "description": "Базовый курс для задач по программированию",
                      "order": 30},
        )

        # Фотографии финалов лежат в репозитории папкой albums/.
        if Path("albums").is_dir():
            call_command("import_photos", "albums", verbosity=0)

        if options["verbosity"]:
            self.stdout.write(self.style.SUCCESS(
                f"Сайт настроен: {season.title}, этапов {len(stages)}. "
                "Администратора создайте командой createsuperuser."
            ))

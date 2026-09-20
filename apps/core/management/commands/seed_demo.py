"""
Наполняет базу демо-данными, чтобы сайт можно было посмотреть сразу после
клонирования репозитория: сезон, этапы, задачи, площадки и пользователи всех ролей.

    python manage.py seed_demo

Команда идемпотентна — повторный запуск ничего не дублирует.
"""

from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import OrganizerProfile, ParticipantProfile, User
from apps.content.models import News, Page, Playlist
from apps.contest.models import Problem, Submission, SubmissionFile
from apps.core.legal_templates import CONSENT_TEXT, PRIVACY_POLICY, RULES_TEXT
from apps.mailing.models import Newsletter
from apps.participation.models import Registration, VenueBooking
from apps.seasons.models import Season, Stage
from apps.seasons.schedule import PRACTICE_STAGE, SEASON_YEAR, STAGES
from apps.venues.models import Venue

DEMO_PASSWORD = "olymp12345"


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные для локальной разработки"

    def handle(self, *args, **options):
        now = timezone.now()

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
        Season.objects.get_or_create(
            year=2026,
            defaults={"slug": "ao26", "title": "Аэрокосмическая олимпиада МФТИ VI",
                      "subtitle": "Сезон 2025/26", "is_published": True},
        )

        # Этапы берём из apps/seasons/schedule.py — там же лежат даты.
        # Именно update_or_create, а не get_or_create: команду запускают
        # и на уже заполненной базе, чтобы разложить новые даты по этапам.
        # Обратная сторона — ручные правки дат в админке она перетирает.
        stages = {}
        for plan in STAGES + [PRACTICE_STAGE]:
            plan = dict(plan)
            slug = plan.pop("slug")
            plan.setdefault("is_practice", False)
            stages[slug], _ = Stage.objects.update_or_create(
                season=season, slug=slug,
                defaults={**plan, "is_published": True},
            )
        online = stages["otbor-1"]
        practice = stages[PRACTICE_STAGE["slug"]]

        # Деления на физику и программирование нет: комплект задач общий.
        demo_problems = [
            (1, "Туннельный гул", 10),
            (2, "Сопло", 12),
            (3, "Долина", 10),
            (4, "Кто чемпион?", 15),
            (5, "Бессонница", 15),
        ]
        for number, title, score in demo_problems:
            Problem.objects.get_or_create(
                stage=online, number=number,
                defaults={"title": title, "max_score": Decimal(score),
                          "status": Problem.Status.APPROVED},
            )

        # Задачи очного тура: без них ведомость площадки пустая и
        # непонятно, куда вписывать баллы.
        for number in (1, 2, 3):
            Problem.objects.get_or_create(
                stage=stages["ochny"], number=number,
                defaults={"title": f"Очная задача {number}",
                          "statement_html": "<p>Условие очной задачи.</p>",
                          "status": Problem.Status.APPROVED},
            )

        Problem.objects.update_or_create(
            stage=practice, number=1,
            defaults={
                "title": "Тренировочная задача",
                "statement_html": (
                    "<p>Это не настоящая задача, а проверка сайта: загрузите любой файл "
                    "и убедитесь, что решение отправляется.</p>"
                    "<p>Что происходит с файлом: он ложится на сервер в "
                    "<code>media/solutions/&lt;сезон&gt;/problem-&lt;id&gt;/user-&lt;id&gt;/</code>, "
                    "а запись о попытке появляется в админке: <b>Дистанционный этап → Решения</b>.</p>"
                    "<p>Тренировочные решения на результаты не влияют, их можно удалять "
                    "из админки в любой момент.</p>"
                ),
                "max_score": None,
                "status": Problem.Status.APPROVED,
            },
        )

        venues = [
            ("Лицей № 1580 при МГТУ им. Баумана", "Москва", "Москва", "ул. Талалихина, 1к1", 55.7376, 37.6798),
            ("Физтех-лицей им. П.Л. Капицы", "Московская область", "Долгопрудный", "ул. Летная, 7", 55.9330, 37.5180),
            ("Лицей № 131", "Республика Татарстан", "Казань", "ул. Волкова, 5", 55.7855, 49.1130),
            ("СУНЦ НГУ", "Новосибирская область", "Новосибирск", "ул. Ляпунова, 3", 54.8430, 83.0920),
        ]
        for title, region, city, address, lat, lon in venues:
            Venue.objects.get_or_create(
                title=title,
                defaults={"region": region, "city": city, "address": address,
                          "latitude": lat, "longitude": lon,
                          "status": Venue.Status.APPROVED},
            )
        for venue in Venue.objects.all():
            venue.seasons.add(season)

        # Каталог лекций прошлых лет — темы, лекции и плейлисты сезонов.
        # Лежит в apps/content/lecture_catalog.py, собран из таблицы
        # организаторов (см. import_lectures).
        call_command("seed_lectures", verbosity=0)

        # Плейлисты, которых нет в таблице сезонов: курс по Python идёт
        # вне сезонов, у двух ВК-плейлистов год не определить.
        playlists = [
            ("Лекции сезона 2021/22", 2022,
             "https://www.youtube.com/watch?v=Z5rYrIb1ER0&list=PLncYbc2UAdLEAZeQOiW2lOEslj-DzC2w8",
             "Разборы задач и подготовка к отборочному этапу", 20),
            ("Лекции сезона 2023/24", 2024,
             "https://www.youtube.com/watch?v=qAsOZwt1UMs&list=PLncYbc2UAdLGmGDtn-7AEPIO5I2fMr12N",
             "Разборы задач и подготовка к отборочному этапу", 10),
            ("Введение в Python", None,
             "https://www.youtube.com/watch?v=vWDNxTdR690&list=PLncYbc2UAdLH3utmw0AKBDg08IXX8GdrP",
             "Базовый курс для задач по программированию", 30),
            ("Лекции во ВКонтакте — часть 1", None,
             "https://vkvideo.ru/playlist/-17906_48144875",
             "Укажите сезон в админке", 40),
            ("Лекции во ВКонтакте — часть 2", None,
             "https://vkvideo.ru/playlist/-17906_48144877",
             "Укажите сезон в админке", 50),
        ]
        for title, year, url, note, order in playlists:
            Playlist.objects.get_or_create(
                url=url,
                defaults={
                    "title": title,
                    "season": self._archive_season(year) if year else None,
                    "description": note,
                    "order": order,
                },
            )

        # Лекции текущего сезона ещё не читались: в разделе «Лекции»
        # пока пусто, и это правда, а не недоработка. Записи прошлых лет
        # лежат в архиве лекций.
        News.objects.get_or_create(
            slug="registration-open",
            defaults={"season": season, "title": "Открыта регистрация на АО VII",
                      "summary": "Регистрация участников началась.",
                      "body": "Регистрация открыта, задачи отборочного этапа появятся в разделе «Дистанционный этап».",
                      "is_published": True},
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

        users = [
            ("admin@example.ru", User.Role.ADMIN, True, True),
            # Отдельной роли «жюри» нет: решения проверяют организаторы.
            ("organizer@example.ru", User.Role.ORGANIZER, True, False),
            ("student@example.ru", User.Role.PARTICIPANT, False, False),
        ]
        for email, role, is_staff, is_superuser in users:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"role": role, "is_staff": is_staff, "is_superuser": is_superuser,
                          # Демо-учётки считаем подтверждёнными: письмо им
                          # никто не отправлял, а баннер «подтвердите почту»
                          # в демо только мешает.
                          "email_confirmed": True},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            if role == User.Role.PARTICIPANT:
                ParticipantProfile.objects.get_or_create(
                    user=user,
                    defaults={"last_name": "Тестов", "first_name": "Пётр", "grade": 10,
                              "city": "Москва", "region": "Москва", "school": "Школа №1",
                              "telegram": "@testov", "consent_given": True,
                              "consent_given_at": now},
                )
                # Записываем в текущий сезон, иначе демо-рассылка
                # по аудитории «участники сезона» найдёт ноль получателей.
                Registration.objects.get_or_create(user=user, season=season, defaults={"grade": 10})
            if role == User.Role.ORGANIZER:
                OrganizerProfile.objects.get_or_create(
                    user=user,
                    defaults={"last_name": "Организаторов", "first_name": "Иван",
                              "phone": "+7 900 000-00-00"},
                )
                venue = Venue.objects.first()
                if venue:
                    venue.managers.add(user)

        # Демо-участник записан на площадку: иначе ведомость пустая.
        first_venue = Venue.objects.filter(managers__isnull=False).first()
        if first_venue and Registration.objects.filter(season=season).exists():
            VenueBooking.objects.get_or_create(
                registration=Registration.objects.filter(season=season).first(),
                stage=stages["ochny"],
                defaults={"venue": first_venue},
            )

        # Автор демо-задач — организатор: иначе в его рабочем месте пусто
        # и непонятно, как устроены правка и проверка. Проставляем после
        # создания пользователей, до него организатора ещё не существует.
        organizer_user = User.objects.filter(role=User.Role.ORGANIZER).first()
        if organizer_user:
            Problem.objects.filter(created_by__isnull=True).update(created_by=organizer_user)

        # Одно решение в очереди проверки: иначе рабочее место организатора
        # выглядит пустым и непонятно, как оно устроено.
        student = User.objects.filter(role=User.Role.PARTICIPANT).first()
        first_problem = Problem.objects.filter(stage=online, number=1).first()
        if student and first_problem and not Submission.objects.filter(
            user=student, problem=first_problem
        ).exists():
            submission = Submission.objects.create(
                user=student, problem=first_problem,
                comment="Решал через закон сохранения импульса, файл во вложении.",
            )
            SubmissionFile.objects.create(
                submission=submission,
                file=ContentFile(
                    b"%PDF-1.4\n% demo solution\n",
                    name="demo-reshenie.pdf",
                ),
            )

        Newsletter.objects.get_or_create(
            subject="Напоминание о дедлайне",
            defaults={
                "body": "Здравствуйте, {{ first_name }}!\n\n"
                        "Напоминаем: приём решений отборочного этапа заканчивается скоро.\n\n"
                        "Аэрокосмическая олимпиада МФТИ",
                "audience": Newsletter.Audience.SEASON_NOT_SUBMITTED,
                "season": season,
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f"Демо-данные созданы. Пользователи: "
            f"{', '.join(e for e, *_ in users)} — пароль «{DEMO_PASSWORD}»"
        ))

    def _archive_season(self, year):
        """
        Сезон прошлых лет для привязки плейлиста.

        Плейлисты заводятся раньше, чем отработает import_archive,
        поэтому недостающий сезон создаём сами — импорт потом его дополнит.
        """
        from apps.content.management.commands.import_archive import roman

        season, _ = Season.objects.get_or_create(
            year=year,
            defaults={
                "slug": f"ao{str(year)[-2:]}",
                "title": f"Аэрокосмическая олимпиада МФТИ {roman(year)}",
                "subtitle": f"Сезон {year - 1}/{str(year)[-2:]}",
                "is_published": True,
            },
        )
        return season

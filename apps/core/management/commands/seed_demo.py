"""
Наполняет базу демо-данными, чтобы сайт можно было посмотреть сразу после
клонирования репозитория: сезон, этапы, задачи, площадки и пользователи всех ролей.

    python manage.py seed_demo

Команда идемпотентна — повторный запуск ничего не дублирует.
"""

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import (
    ConsentDocument,
    DocumentType,
    OrganizerProfile,
    ParticipantProfile,
    User,
)
from apps.contest.models import Problem, Submission, SubmissionFile
from apps.mailing.models import Newsletter
from apps.participation.models import Registration, VenueBooking
from apps.seasons.models import Season
from apps.seasons.schedule import PRACTICE_STAGE, SEASON_YEAR
from apps.venues.models import Venue

DEMO_PASSWORD = "olymp12345"


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные для локальной разработки"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="запустить и при DEBUG=False (только для проверки Docker-сборки у себя)",
        )

    def handle(self, *args, **options):
        # На боевом сервере демо-данные — дыра: учётка admin@example.ru
        # с паролем из README и выдуманные площадки, на которые начнут
        # записываться школьники. Для сервера есть setup_site.
        if not settings.DEBUG and not settings.TESTING and not options["force"]:
            raise CommandError(
                "Похоже, это боевой сервер (DEBUG=False): демо-данные сюда не нужны.\n"
                "Для настройки сайта: python manage.py setup_site\n"
                "Если это проверка Docker-сборки у себя — добавьте --force."
            )
        now = timezone.now()

        # Всё, что есть и на настоящем сайте: сезон, этапы, тренировочная
        # задача, страницы, лекции, фото. Локально даты этапов берём из
        # schedule.py заново, чтобы у всех разработчиков они совпадали.
        call_command("setup_site", update_dates=True, verbosity=0)
        season = Season.objects.get(year=SEASON_YEAR)
        Season.objects.get_or_create(
            year=2026,
            defaults={"slug": "ao26", "title": "Аэрокосмическая олимпиада МФТИ VI",
                      "subtitle": "Сезон 2025/26", "is_published": True},
        )
        stages = {stage.slug: stage for stage in season.stages.all()}
        practice = stages[PRACTICE_STAGE["slug"]]

        # Задач дистанционного этапа в демо нет, как и на настоящем сайте
        # до 15 ноября: их заводят организаторы и одобряет администратор.
        # Задачи очного тура нужны, иначе ведомость площадки пустая и
        # непонятно, куда вписывать баллы.
        for number in (1, 2, 3):
            Problem.objects.get_or_create(
                stage=stages["ochny"], number=number,
                defaults={"title": f"Очная задача {number}",
                          "statement_html": "<p>Условие очной задачи.</p>",
                          "max_score": Decimal(10),
                          "status": Problem.Status.APPROVED},
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
            if not user.email_confirmed:
                user.email_confirmed = True
                user.save(update_fields=["email_confirmed"])
            if role == User.Role.PARTICIPANT:
                # Анкета заполнена целиком и согласие принято: демо-участник
                # может записываться на площадку и сдавать решения. Данные
                # документов выдуманные.
                profile, _ = ParticipantProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "last_name": "Тестов", "first_name": "Пётр", "middle_name": "Иванович",
                        "birth_date": date(2010, 3, 14), "grade": 10,
                        "city": "Москва", "region": "Москва", "school": "Школа №1",
                        "phone": "+7 900 000-00-01", "telegram": "@testov",
                        "doc_type": DocumentType.PASSPORT_RF, "doc_series": "0000",
                        "doc_number": "000000",
                        "doc_issued_at": date(2024, 3, 20), "doc_issued_by": "ГУ МВД России по г. Москве",
                        "reg_address": "101000, г. Москва, ул. Примерная, д. 1, кв. 1",
                        "consent_given": True, "consent_given_at": now,
                    },
                )
                if not user.consents.exists():
                    ConsentDocument.objects.create(
                        user=user, for_minor=True, data=profile.consent_data(),
                        status=ConsentDocument.Status.APPROVED,
                        file=ContentFile(b"%PDF-1.4\n% demo consent\n", name="soglasie.pdf"),
                        original_name="soglasie.pdf",
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
        first_problem = Problem.objects.filter(stage=practice, number=1).first()
        if student and first_problem and not Submission.objects.filter(
            user=student, problem=first_problem
        ).exists():
            submission = Submission.objects.create(
                user=student, problem=first_problem,
                comment="Проверяю, что загрузка работает.",
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

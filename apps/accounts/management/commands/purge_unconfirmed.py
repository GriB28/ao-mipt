"""
Удаляет регистрации, почту которых так и не подтвердили.

    python manage.py purge_unconfirmed            # старше 14 дней
    python manage.py purge_unconfirmed --days 30

Без подтверждения в кабинет не войти, поэтому за такими записями ничего
нет: ни анкеты, ни решений. Хранить чужие или ошибочные адреса незачем —
это тоже персональные данные. Запускается контейнером mailer раз в час.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Удаляет неподтверждённые регистрации участников старше N дней"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = User.objects.filter(role=User.Role.PARTICIPANT, email_confirmed=False,
                                    is_staff=False, date_joined__lt=cutoff)
        count = stale.count()
        stale.delete()
        if count or options["verbosity"] > 1:
            self.stdout.write(f"Удалено неподтверждённых регистраций: {count}")

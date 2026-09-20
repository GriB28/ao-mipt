"""
Отправляет порцию писем из очереди.

Запускать по cron раз в минуту:
    * * * * * cd /srv/olymp && docker compose exec -T web python manage.py send_newsletters

Команда безопасна для повторного запуска: уже отправленные письма
пропускаются, упавшая отправка продолжится с места остановки.
"""

from django.core.management.base import BaseCommand

from apps.mailing.services import BATCH_SIZE, send_pending


class Command(BaseCommand):
    help = "Отправляет письма, стоящие в очереди рассылок"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=BATCH_SIZE,
                            help=f"сколько писем отправить за запуск (по умолчанию {BATCH_SIZE})")

    def handle(self, *args, **options):
        stats = send_pending(limit=options["limit"])
        if stats["sent"] or stats["failed"]:
            self.stdout.write(self.style.SUCCESS(
                f"Отправлено: {stats['sent']}, ошибок: {stats['failed']}"
            ))

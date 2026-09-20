"""Логика постановки в очередь и отправки. Отдельно от моделей и админки."""

import logging

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.message import EmailMessage
from django.db import transaction
from django.template import Context, Template
from django.utils import timezone

from .models import Delivery, Newsletter

logger = logging.getLogger(__name__)

# Сколько писем шлём за один запуск команды. SMTP-релеи обычно
# ограничивают частоту, поэтому лучше слать порциями раз в минуту.
BATCH_SIZE = 100


@transaction.atomic
def queue_newsletter(newsletter: Newsletter) -> int:
    """Создаёт задания на отправку. Возвращает число получателей."""
    recipients = list(newsletter.get_recipients())
    Delivery.objects.bulk_create(
        [Delivery(newsletter=newsletter, user=u, email=u.email) for u in recipients],
        ignore_conflicts=True,  # повторная постановка не продублирует письма
    )
    newsletter.status = Newsletter.Status.QUEUED
    newsletter.queued_at = timezone.now()
    newsletter.finished_at = None
    newsletter.last_error = ""
    newsletter.save(update_fields=["status", "queued_at", "finished_at", "last_error", "updated_at"])
    return len(recipients)


def render_body(newsletter: Newsletter, user) -> str:
    """Подставляет имя получателя в текст письма."""
    profile = getattr(user, "profile", None)
    context = Context({
        "first_name": getattr(profile, "first_name", "") or "",
        "last_name": getattr(profile, "last_name", "") or "",
        "email": user.email,
    })
    return Template(newsletter.body).render(context)


def send_pending(limit: int = BATCH_SIZE) -> dict:
    """
    Отправляет очередную порцию писем. Вызывается командой send_newsletters.
    Возвращает статистику по отправке.
    """
    pending = (Delivery.objects
               .filter(status=Delivery.Status.PENDING,
                       newsletter__status__in=[Newsletter.Status.QUEUED, Newsletter.Status.SENDING])
               .select_related("newsletter", "user", "user__profile")[:limit])

    stats = {"sent": 0, "failed": 0}
    if not pending:
        _finish_completed_newsletters()
        return stats

    # Одно SMTP-соединение на всю порцию — иначе сервер отвергнет
    # сотню подряд идущих подключений.
    connection = get_connection()
    try:
        connection.open()
    except Exception as exc:
        logger.error("Не удалось подключиться к SMTP: %s", exc)
        Newsletter.objects.filter(pk__in={d.newsletter_id for d in pending}).update(
            status=Newsletter.Status.FAILED, last_error=str(exc)
        )
        return stats

    for delivery in pending:
        Newsletter.objects.filter(pk=delivery.newsletter_id, status=Newsletter.Status.QUEUED).update(
            status=Newsletter.Status.SENDING
        )
        try:
            message = EmailMessage(
                subject=delivery.newsletter.subject,
                body=render_body(delivery.newsletter, delivery.user),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[delivery.email],
                connection=connection,
            )
            message.send(fail_silently=False)
        except Exception as exc:
            delivery.status = Delivery.Status.FAILED
            delivery.error = str(exc)[:1000]
            stats["failed"] += 1
            logger.warning("Письмо на %s не ушло: %s", delivery.email, exc)
        else:
            delivery.status = Delivery.Status.SENT
            delivery.sent_at = timezone.now()
            delivery.error = ""
            stats["sent"] += 1
        delivery.save(update_fields=["status", "error", "sent_at", "updated_at"])

    connection.close()
    _finish_completed_newsletters()
    return stats


def _finish_completed_newsletters():
    """Помечает рассылки, у которых не осталось ожидающих писем."""
    active = Newsletter.objects.filter(
        status__in=[Newsletter.Status.QUEUED, Newsletter.Status.SENDING]
    )
    for newsletter in active:
        if not newsletter.deliveries.filter(status=Delivery.Status.PENDING).exists():
            newsletter.status = Newsletter.Status.SENT
            newsletter.finished_at = timezone.now()
            newsletter.save(update_fields=["status", "finished_at", "updated_at"])

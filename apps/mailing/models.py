"""
Рассылки участникам.

Почему через очередь, а не «отправить прямо сейчас по кнопке»:
тысяча писем через SMTP — это несколько минут, за которые браузер
отвалится по таймауту, а половина писем уйдёт дважды при повторном нажатии.
Поэтому админ ставит рассылку в очередь, а отправляет её отдельная команда
(`manage.py send_newsletters`), запускаемая по cron раз в минуту.

Каждому получателю создаётся своя запись Delivery. Это даёт:
  * идемпотентность — повторный запуск не пошлёт письмо дважды;
  * возобновление — если процесс упал на 500-м письме, продолжим с 501-го;
  * ответ на вопрос «а Петрову письмо дошло?».
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.seasons.models import Season


class Newsletter(TimeStampedModel):
    class Audience(models.TextChoices):
        ALL_PARTICIPANTS = "all_participants", "Все зарегистрированные участники"
        SEASON_PARTICIPANTS = "season", "Участники выбранного сезона"
        SEASON_SUBMITTED = "submitted", "Сдавшие хотя бы одну задачу в сезоне"
        SEASON_NOT_SUBMITTED = "not_submitted", "Зарегистрированные, но ничего не сдавшие"
        VENUE_BOOKED = "venue_booked", "Записавшиеся на очный тур"
        VENUE_PARTICIPANTS = "venue", "Записавшиеся на выбранную площадку"
        ORGANIZERS = "organizers", "Организаторы"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        QUEUED = "queued", "В очереди на отправку"
        SENDING = "sending", "Отправляется"
        SENT = "sent", "Отправлена"
        FAILED = "failed", "Ошибка"

    subject = models.CharField("тема письма", max_length=250)
    body = models.TextField(
        "текст письма",
        help_text="Можно использовать {{ first_name }} и {{ last_name }} — подставится имя получателя.",
    )

    audience = models.CharField("кому", max_length=20, choices=Audience.choices,
                                default=Audience.ALL_PARTICIPANTS)
    season = models.ForeignKey(Season, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name="сезон",
                               help_text="Нужен для аудиторий, привязанных к сезону.")
    venue = models.ForeignKey("venues.Venue", on_delete=models.CASCADE, null=True, blank=True,
                              related_name="newsletters", verbose_name="площадка",
                              help_text="Нужна для рассылки по одной площадке.")

    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, verbose_name="автор")
    queued_at = models.DateTimeField("поставлена в очередь", null=True, blank=True)
    finished_at = models.DateTimeField("отправка завершена", null=True, blank=True)
    last_error = models.TextField("последняя ошибка", blank=True)

    class Meta:
        verbose_name = "рассылка"
        verbose_name_plural = "рассылки"
        ordering = ["-created_at"]

    def __str__(self):
        return self.subject

    def get_recipients(self):
        """Кому уйдёт письмо. Возвращает QuerySet пользователей."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        # Пишем только тем, кто активен и подтвердил почту —
        # иначе половина писем уйдёт в никуда и испортит репутацию домена.
        base = User.objects.filter(is_active=True).exclude(email="")

        a = self.Audience
        if self.audience == a.ALL_PARTICIPANTS:
            return base.filter(role=User.Role.PARTICIPANT)
        if self.audience == a.ORGANIZERS:
            return base.filter(role=User.Role.ORGANIZER)
        if self.audience == a.VENUE_PARTICIPANTS:
            # Единственная аудитория, которой сезон не нужен: площадка
            # уже задаёт и сезон, и круг людей.
            if not self.venue:
                return base.none()
            return (base.filter(registrations__bookings__venue=self.venue)
                        .exclude(registrations__bookings__status="cancelled")
                        .distinct())

        if not self.season:
            return base.none()

        if self.audience == a.SEASON_PARTICIPANTS:
            return base.filter(registrations__season=self.season).distinct()
        if self.audience == a.SEASON_SUBMITTED:
            return base.filter(submissions__problem__stage__season=self.season).distinct()
        if self.audience == a.SEASON_NOT_SUBMITTED:
            return (base.filter(registrations__season=self.season)
                        .exclude(submissions__problem__stage__season=self.season)
                        .distinct())
        if self.audience == a.VENUE_BOOKED:
            return (base.filter(registrations__bookings__stage__season=self.season)
                        .exclude(registrations__bookings__status="cancelled")
                        .distinct())
        return base.none()

    @property
    def recipients_count(self):
        return self.get_recipients().count()

    @property
    def sent_count(self):
        return self.deliveries.filter(status=Delivery.Status.SENT).count()

    @property
    def failed_count(self):
        return self.deliveries.filter(status=Delivery.Status.FAILED).count()


class Delivery(TimeStampedModel):
    """Одно письмо одному человеку."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"

    newsletter = models.ForeignKey(Newsletter, on_delete=models.CASCADE,
                                   related_name="deliveries", verbose_name="рассылка")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             verbose_name="получатель")
    email = models.EmailField("адрес")
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.TextField("ошибка", blank=True)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        verbose_name = "письмо"
        verbose_name_plural = "письма"
        constraints = [
            models.UniqueConstraint(fields=["newsletter", "user"], name="one_delivery_per_user"),
        ]
        indexes = [models.Index(fields=["newsletter", "status"])]

    def __str__(self):
        return f"{self.email} — {self.get_status_display()}"

"""
Участие в сезоне и запись на площадку очного тура.
"""

from django.conf import settings
from django.db import models, transaction

from apps.core.models import TimeStampedModel
from apps.seasons.models import Season, Stage
from apps.venues.models import Venue


class Registration(TimeStampedModel):
    """Факт участия человека в конкретном сезоне."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="registrations", verbose_name="пользователь")
    season = models.ForeignKey(Season, on_delete=models.CASCADE,
                               related_name="registrations", verbose_name="сезон")
    grade = models.PositiveSmallIntegerField("класс на момент регистрации", null=True, blank=True)

    class Meta:
        verbose_name = "участие в сезоне"
        verbose_name_plural = "участие в сезонах"
        constraints = [
            models.UniqueConstraint(fields=["user", "season"], name="unique_registration_per_season"),
        ]

    def __str__(self):
        return f"{self.user} — {self.season}"


class VenueBookingError(Exception):
    """Не удалось записаться: нет мест или запись закрыта."""


class VenueBooking(TimeStampedModel):
    """Запись участника на площадку очного тура."""

    class Status(models.TextChoices):
        BOOKED = "booked", "Записан"
        CONFIRMED = "confirmed", "Подтверждён"
        ATTENDED = "attended", "Пришёл"
        CANCELLED = "cancelled", "Отменена"

    registration = models.ForeignKey(Registration, on_delete=models.CASCADE,
                                     related_name="bookings", verbose_name="участие")
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE,
                              related_name="bookings", verbose_name="этап")
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT,
                              related_name="bookings", verbose_name="площадка")
    status = models.CharField("статус", max_length=12, choices=Status.choices, default=Status.BOOKED)
    comment = models.TextField("комментарий", blank=True)

    class Meta:
        verbose_name = "запись на площадку"
        verbose_name_plural = "записи на площадки"
        constraints = [
            models.UniqueConstraint(fields=["registration", "stage"], name="one_venue_per_stage"),
        ]

    def __str__(self):
        return f"{self.registration.user} → {self.venue}"

    @classmethod
    @transaction.atomic
    def book(cls, registration, stage, venue):
        """
        Записать участника на площадку.

        Ограничения по числу мест нет: если на площадку запишется больше
        людей, чем она вмещает, организаторы договариваются вручную.
        Перезапись на другую площадку заменяет прежнюю, а не добавляет вторую.
        """
        if not stage.registration_is_open:
            raise VenueBookingError("Запись на этот этап сейчас закрыта.")
        if not venue.is_public:
            raise VenueBookingError("Площадка недоступна для записи.")
        booking, _ = cls.objects.update_or_create(
            registration=registration, stage=stage,
            defaults={"venue": venue, "status": cls.Status.BOOKED},
        )
        return booking

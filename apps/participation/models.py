import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_upload_size
from apps.seasons.models import Season, Stage
from apps.venues.models import Venue


def offline_scan_upload_path(instance, filename):
    season = instance.stage.season.slug
    stage = instance.stage.slug
    user_id = instance.registration.user_id
    ext = Path(filename).suffix.lower()
    return f"scans/{season}/{stage}/user-{user_id}/scan{ext}"


def validate_pdf_scan(file):
    validate_upload_size(file)
    ext = Path(file.name).suffix.lower()
    if ext != ".pdf":
        raise ValidationError("Файл должен быть в формате PDF.")


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
    held_at = models.DateField(
        "дата проведения", null=True, blank=True,
        help_text="Фактическая дата проведения тура для участника",
    )
    variant = models.PositiveSmallIntegerField(
        "комплект", choices=[(1, "Комплект 1"), (2, "Комплект 2")],
        null=True, blank=True,
        help_text="Комплект заданий участника. Если не указан — берётся из площадки",
    )
    work_scan = models.FileField(
        "скан работы (PDF)", upload_to=offline_scan_upload_path, blank=True,
        validators=[validate_pdf_scan],
        help_text="Единый PDF-файл со сканом всей работы участника",
    )

    class Meta:
        verbose_name = "запись на площадку"
        verbose_name_plural = "записи на площадки"
        constraints = [
            models.UniqueConstraint(fields=["registration", "stage"], name="one_venue_per_stage"),
        ]

    def __str__(self):
        return f"{self.registration.user} → {self.venue}"

    @property
    def effective_variant(self) -> int:
        return self.variant or (self.venue and self.venue.default_variant) or 1

    @property
    def effective_held_at(self):
        return self.held_at or (self.venue and self.venue.event_date)

    def can_view_scan(self, user) -> bool:
        if not user.is_authenticated:
            return False
        if user.is_manager:
            return True
        return self.registration.user_id == user.pk and self.stage.results_published

    def get_scan_url(self):
        if not self.work_scan:
            return ""
        return reverse("venues:work_scan", args=[self.pk])

    @property
    def can_cancel(self) -> bool:
        """Можно ли участнику отменить эту запись.

        Запрещено, если очный этап прошёл: либо на самой площадке тур завершился
        (venue.stage_passed), либо наступил дедлайн очного этапа (stage.is_past).
        """
        if self.venue and self.venue.stage_passed:
            return False
        if self.stage and self.stage.is_past:
            return False
        return True

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
        if venue.registration_closed:
            raise VenueBookingError("Запись на эту площадку заблокирована организаторами.")
        if venue.stage_passed:
            raise VenueBookingError("Запись на эту площадку закрыта: очный этап уже прошёл.")

        current_booking = cls.objects.filter(
            registration=registration, stage=stage
        ).exclude(status=cls.Status.CANCELLED).select_related("venue").first()

        if current_booking and current_booking.venue_id != venue.pk:
            if not current_booking.can_cancel or venue.stage_passed:
                raise VenueBookingError("Нельзя сменить площадку: очный этап уже прошёл.")

        booking, _ = cls.objects.update_or_create(
            registration=registration, stage=stage,
            defaults={"venue": venue, "status": cls.Status.BOOKED},
        )
        return booking

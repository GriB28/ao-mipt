"""
Площадки очного тура: школы, которые принимают участников у себя.

Жизненный цикл: организатор создаёт заявку (DRAFT → PENDING),
администратор одобряет (APPROVED), после чего площадка появляется
на публичной карте и на неё можно записываться.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.seasons.models import Season


class VenueQuerySet(models.QuerySet):
    def public(self):
        return self.filter(status=Venue.Status.APPROVED, is_visible=True)

    def for_season(self, season):
        return self.filter(seasons=season) if season else self.none()

    def managed_by(self, user):
        """Площадки, за которые отвечает этот человек.

        Администратор видит все: ему и модерировать, и отвечать на вопросы
        по чужим площадкам. Организатор — только свои, из Venue.managers.
        """
        # Импорт внутри метода: venues не должен зависеть от accounts
        # на уровне модуля, иначе получится кольцо импортов.
        from apps.accounts.models import User

        if not user.is_authenticated:
            return self.none()
        if user.is_superuser or user.role == User.Role.ADMIN:
            return self.all()
        return self.filter(managers=user)


class Venue(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PENDING = "pending", "На модерации"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отклонена"

    title = models.CharField("название площадки", max_length=250, help_text="Например: Лицей №1580, г. Москва")
    short_title = models.CharField("короткое название", max_length=100, blank=True)
    description = models.TextField("описание", blank=True, help_text="Как пройти, какой вход, что взять с собой")

    # Регион выбирается из списка (apps/accounts/regions.py) — иначе
    # в базе заводятся «Москва», «г. Москва» и «МСК» как разные регионы.
    region = models.CharField("регион", max_length=120)
    city = models.CharField("город", max_length=120)
    address = models.CharField("адрес", max_length=300)
    latitude = models.FloatField("широта", validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.FloatField("долгота", validators=[MinValueValidator(-180), MaxValueValidator(180)])

    contact_name = models.CharField("контактное лицо", max_length=150, blank=True)
    # Телефон или телеграм — хотя бы одно: школьнику и его родителям нужен
    # способ быстро связаться с площадкой, а чем именно пользуется
    # ответственный, решает он сам.
    contact_phone = models.CharField("телефон", max_length=32, blank=True)
    contact_telegram = models.CharField("Telegram", max_length=64, blank=True,
                                        help_text="Например: @ivanov")
    contact_email = models.EmailField("e-mail", blank=True)

    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    moderation_comment = models.TextField("комментарий модератора", blank=True)
    is_visible = models.BooleanField("показывать на карте", default=True)

    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="managed_venues", blank=True,
        verbose_name="организаторы", help_text="Кто отвечает за эту площадку",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_venues", verbose_name="кто подал заявку",
    )
    seasons = models.ManyToManyField(Season, related_name="venues", blank=True, verbose_name="сезоны")

    objects = VenueQuerySet.as_manager()

    class Meta:
        verbose_name = "площадка"
        verbose_name_plural = "площадки"
        ordering = ["region", "city", "title"]
        indexes = [models.Index(fields=["status", "is_visible"])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("venues:detail", args=[self.pk])

    @property
    def is_public(self):
        return self.status == self.Status.APPROVED and self.is_visible

    def booked_count(self, stage=None):
        """Сколько человек записалось. Ограничения сверху нет:
        если народу приходит больше, чем помещается, договариваемся вручную."""
        qs = self.bookings.exclude(status="cancelled")
        if stage:
            qs = qs.filter(stage=stage)
        return qs.count()

    def as_geojson_feature(self, stage=None):
        """Одна точка для карты Leaflet."""
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "properties": {
                "id": self.pk,
                "title": self.title,
                "city": self.city,
                "region": self.region,
                "address": self.address,
                "booked": self.booked_count(stage),
                "url": self.get_absolute_url(),
            },
        }

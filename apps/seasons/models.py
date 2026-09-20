"""
Сезон — один год олимпиады. Почти всё в проекте привязано к сезону,
поэтому архив прошлых лет получается тем же кодом, что и текущий год.

Деления на направления и возрастные группы нет: задачи одни для всех
классов, физика и программирование идут общим комплектом.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class SeasonQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)

    def active(self):
        return self.published().filter(is_active=True).first()


class Season(TimeStampedModel):
    """Например: АО VII, учебный год 2026/27."""

    year = models.PositiveSmallIntegerField("год завершения", unique=True, help_text="2027 для сезона 2026/27")
    slug = models.SlugField("адрес", unique=True, help_text="используется в URL: /archive/ao27/")
    title = models.CharField("название", max_length=150)
    subtitle = models.CharField("подзаголовок", max_length=250, blank=True)
    description = models.TextField("описание", blank=True)
    accent_color = models.CharField(
        "цвет сезона", max_length=7, default="#2f6fed",
        help_text="HEX, используется в оформлении: #2f6fed",
    )
    logo = models.ImageField("логотип", upload_to="seasons/", blank=True)
    is_active = models.BooleanField(
        "текущий сезон", default=False,
        help_text="Активным может быть только один сезон — он показывается на главной.",
    )
    is_published = models.BooleanField("опубликован", default=False)

    objects = SeasonQuerySet.as_manager()

    class Meta:
        verbose_name = "сезон"
        verbose_name_plural = "сезоны"
        ordering = ["-year"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Активный сезон ровно один: при назначении нового снимаем флаг с остальных.
        if self.is_active:
            Season.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
        super().save(*args, **kwargs)


class StageQuerySet(models.QuerySet):
    def real(self):
        """Настоящие туры — без тренировочной песочницы."""
        return self.filter(is_practice=False)

    def current_or_next(self, season, kind):
        """Какой тур этого формата показывать на вкладке.

        Сначала тот, что идёт прямо сейчас; если ни один не идёт — ближайший
        предстоящий; если все прошли — последний. Брать просто «первый по
        дате» нельзя: в феврале вкладка задач так и показывала бы закрытый
        ноябрьский отбор вместо второго этапа.
        """
        if season is None:
            return None
        now = timezone.now()
        base = self.real().filter(season=season, kind=kind, is_published=True)
        return (base.filter(starts_at__lte=now, ends_at__gte=now).order_by("starts_at").first()
                or base.filter(ends_at__gte=now).order_by("starts_at").first()
                or base.order_by("-starts_at").first())

    def next_upcoming(self, season):
        if season is None:
            return None
        now = timezone.now()
        return (self.real()
                .filter(season=season, is_published=True, ends_at__gte=now)
                .order_by("starts_at").first())


class Stage(TimeStampedModel):
    """Этап сезона: дистанционный отбор, очный финал."""

    class Kind(models.TextChoices):
        ONLINE = "online", "Только дистанционно"
        OFFLINE = "offline", "Только очно"
        HYBRID = "hybrid", "Дистанционно или на площадке"

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="stages", verbose_name="сезон")
    kind = models.CharField("формат", max_length=10, choices=Kind.choices)
    order = models.PositiveSmallIntegerField(
        "порядок", default=1,
        help_text="1 — первый отборочный, 2 — второй отборочный, 3 — финал. "
                  "У равноценных форматов одного тура порядок совпадает: "
                  "очный и дистанционный первый отбор — это один этап, "
                  "пройти нужно что-то одно.",
    )
    requires_proctoring = models.BooleanField(
        "с прокторингом", default=False,
        help_text="Работа выполняется под наблюдением через камеру",
    )
    short_note = models.CharField(
        "даты на схеме", max_length=120, blank=True,
        help_text="Короткая строка под названием этапа: «19–24 октября»",
    )
    place = models.CharField(
        "место проведения", max_length=120, blank=True,
        help_text="Показывается на схеме отдельной строкой: «Кампус МФТИ»",
    )
    slug = models.SlugField("адрес")
    title = models.CharField("название", max_length=150)
    description = models.TextField("описание", blank=True)

    starts_at = models.DateTimeField("начало")
    ends_at = models.DateTimeField("дедлайн")
    results_at = models.DateTimeField("публикация результатов", null=True, blank=True)
    results_published = models.BooleanField(
        "результаты опубликованы", default=False,
        help_text="Пока галочки нет, баллы видят только организаторы. "
                  "Снимается и ставится вручную — ведомость должна быть готова целиком",
    )

    registration_opens_at = models.DateTimeField("запись открывается", null=True, blank=True)
    registration_closes_at = models.DateTimeField("запись закрывается", null=True, blank=True)

    is_published = models.BooleanField("опубликован", default=False)
    platform_url = models.URLField(
        "внешняя платформа", blank=True,
        help_text="Если тур проходит не на нашем сайте: например, "
                  "https://exams.mipt.ru для этапа с прокторингом",
    )
    is_practice = models.BooleanField(
        "тренировочный", default=False,
        help_text="Служебный этап-песочница: не показывается как текущий тур, "
                  "нужен, чтобы проверить загрузку решений в любой момент",
    )

    objects = StageQuerySet.as_manager()

    class Meta:
        verbose_name = "этап"
        verbose_name_plural = "этапы"
        ordering = ["order", "starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["season", "slug"], name="unique_stage_slug_per_season"),
        ]

    def __str__(self):
        return f"{self.season.title} — {self.title}"

    def clean(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError({"ends_at": "Дедлайн должен быть позже начала."})

    @property
    def has_online(self) -> bool:
        return self.kind in (self.Kind.ONLINE, self.Kind.HYBRID)

    @property
    def has_offline(self) -> bool:
        return self.kind in (self.Kind.OFFLINE, self.Kind.HYBRID)

    @property
    def is_open(self) -> bool:
        """Идёт ли приём решений прямо сейчас."""
        now = timezone.now()
        return self.is_published and self.starts_at <= now <= self.ends_at

    @property
    def registration_is_open(self) -> bool:
        """Идёт ли запись на площадки.

        Если дата закрытия не указана, запись остаётся открытой и после
        тура: на площадку приходят люди без регистрации, и организатору
        нужно завести их задним числом.
        """
        now = timezone.now()
        opens = self.registration_opens_at or self.starts_at
        if not (self.is_published and opens <= now):
            return False
        return self.registration_closes_at is None or now <= self.registration_closes_at

"""
Дистанционный этап: задачи, решения участников, проверка организаторами.

Заменяет нынешний процесс «скачать архив решений → проверить →
забить баллы в Excel»: очередь проверки и баллы живут в базе,
выгрузка в Excel остаётся кнопкой, а не источником истины.
"""

import secrets
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_solution_file, validate_upload_size
from apps.seasons.models import Stage


def problem_upload_path(instance, filename):
    """Куда кладём файлы задачи: рисунок, PDF, материалы.

    Общая для Problem и ProblemAttachment (у вложения этап берём через
    задачу). Случайная папка в пути — чтобы файлы ещё не открытой задачи
    нельзя было скачать до начала тура, угадав имя вроде «risunok.png»:
    /media/ отдаётся без проверки прав.
    """
    stage = instance.problem.stage if hasattr(instance, "problem_id") else instance.stage
    return f"problems/{stage.season.slug}/{stage.slug}/{secrets.token_urlsafe(12)}/{filename}"


def solution_upload_path(instance, filename):
    sub = instance.submission
    season = sub.problem.stage.season.slug
    return f"solutions/{season}/problem-{sub.problem_id}/user-{sub.user_id}/{filename}"


class ProblemQuerySet(models.QuerySet):
    def visible(self):
        """Задача видна участникам: одобрена и этап уже начался.

        Время публикации общее для всех задач этапа — это начало этапа,
        оно задаётся в админке (Сезоны → Этапы). Задачи заводят и
        одобряют заранее, и открываются они все разом.
        """
        return self.filter(
            stage__is_published=True,
            stage__starts_at__lte=timezone.now(),
            status=Problem.Status.APPROVED,
        )

    def editable_by(self, user):
        """Задачи, которые человек вправе открыть в рабочем месте организатора.

        Администратор видит все — ему их одобрять. Организатор видит свои
        и те, куда его назначили дополнительным проверяющим.
        """
        from apps.accounts.models import User

        if not user.is_authenticated:
            return self.none()
        if user.is_superuser or user.role == User.Role.ADMIN:
            return self.all()
        return self.filter(models.Q(created_by=user) | models.Q(reviewers=user)).distinct()


class Problem(TimeStampedModel):
    """
    Задача тура.

    Путь задачи: организатор заводит черновик → отправляет на одобрение →
    администратор одобряет, и только после этого её видят участники.
    Проверять решения могут автор задачи и назначенные администратором
    дополнительные проверяющие.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PENDING = "pending", "На одобрении"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отклонена"

    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="problems", verbose_name="этап")
    number = models.PositiveSmallIntegerField("номер", default=1)
    title = models.CharField("название", max_length=250)
    statement_html = models.TextField(
        "условие", blank=True,
        help_text="Формулы в долларах: $E = mc^2$ в строке, $$...$$ отдельным блоком (LaTeX)",
    )
    statement_pdf = models.FileField(
        "условие (PDF)", upload_to=problem_upload_path, blank=True,
        validators=[validate_upload_size], help_text="Если условие удобнее отдать файлом",
    )
    figure = models.ImageField(
        "рисунок к условию", upload_to=problem_upload_path, blank=True,
        validators=[validate_upload_size],
        help_text="Схема или график, показывается прямо под условием",
    )
    figure_caption = models.CharField("подпись к рисунку", max_length=250, blank=True)

    # Максимум не показывается участникам и не обязателен: шкала может
    # уточняться уже по ходу проверки. Если задан — форма оценки не даст
    # поставить больше, это ловит опечатки вроде «100» вместо «10».
    max_score = models.DecimalField("максимальный балл", max_digits=6, decimal_places=2,
                                    null=True, blank=True,
                                    help_text="Необязательно. Участникам не показывается")

    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    moderation_comment = models.TextField("комментарий администратора", blank=True,
                                          help_text="Виден автору задачи, если задача отклонена")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="authored_problems", verbose_name="автор задачи",
    )
    reviewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="reviewed_problems",
        verbose_name="дополнительные проверяющие",
        help_text="Кроме автора задачи. Назначает администратор",
    )

    solution_pdf = models.FileField("разбор (PDF)", upload_to=problem_upload_path, blank=True,
                                    validators=[validate_upload_size])
    solution_published_at = models.DateTimeField("разбор доступен с", null=True, blank=True)

    objects = ProblemQuerySet.as_manager()

    class Meta:
        verbose_name = "задача"
        verbose_name_plural = "задачи"
        ordering = ["stage", "number"]
        constraints = [
            models.UniqueConstraint(fields=["stage", "number"], name="unique_problem_number_per_stage"),
        ]

    def __str__(self):
        return f"{self.number}. {self.title}"

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    def can_be_reviewed_by(self, user) -> bool:
        """Кто вправе проверять решения этой задачи."""
        from apps.accounts.models import User

        if not user.is_authenticated:
            return False
        if user.is_superuser or user.role == User.Role.ADMIN:
            return True
        return self.created_by_id == user.pk or self.reviewers.filter(pk=user.pk).exists()

    @property
    def accepts_submissions(self):
        return self.stage.is_open

    @property
    def solution_is_public(self):
        return bool(self.solution_pdf) and (
            self.solution_published_at is not None and self.solution_published_at <= timezone.now()
        )


class ProblemAttachment(TimeStampedModel):
    """Данные к задаче: signal.txt, csv с измерениями, картинки."""

    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="attachments", verbose_name="задача")
    title = models.CharField("название", max_length=200, blank=True)
    file = models.FileField("файл", upload_to=problem_upload_path, validators=[validate_upload_size])

    class Meta:
        verbose_name = "материал к задаче"
        verbose_name_plural = "материалы к задачам"

    def __str__(self):
        return self.title or self.file.name


class Submission(TimeStampedModel):
    """
    Одна попытка сдачи. Новая попытка не удаляет старую —
    при спорах важно видеть, что и когда было отправлено.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="submissions", verbose_name="участник")
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE,
                                related_name="submissions", verbose_name="задача")
    comment = models.TextField("комментарий участника", blank=True)
    answer = models.CharField("ответ", max_length=250, blank=True,
                              help_text="Для задач с числовым ответом")
    is_latest = models.BooleanField("последняя попытка", default=True)
    is_late = models.BooleanField("после дедлайна", default=False)

    class Meta:
        verbose_name = "решение"
        verbose_name_plural = "решения"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["problem", "is_latest"])]

    def __str__(self):
        return f"{self.user} — задача {self.problem.number}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if is_new:
            self.is_late = timezone.now() > self.problem.stage.ends_at
        super().save(*args, **kwargs)
        if is_new:
            # Прошлые попытки по этой задаче перестают быть текущими.
            Submission.objects.filter(user=self.user, problem=self.problem).exclude(pk=self.pk).update(is_latest=False)

    def can_be_viewed_by(self, user) -> bool:
        """Кто вправе открыть файлы решения: сам участник и проверяющие задачи."""
        if not user.is_authenticated:
            return False
        return self.user_id == user.pk or self.problem.can_be_reviewed_by(user)

    @property
    def visible_grade(self):
        """Оценка, которую уже можно показать участнику, или None.

        Пока результаты этапа не опубликованы, участник видит только
        статус проверки: балл и комментарий появляются вместе со всеми.
        """
        grade = getattr(self, "grade", None)
        if grade and self.problem.stage.results_published:
            return grade
        return None


class SubmissionFile(TimeStampedModel):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE,
                                   related_name="files", verbose_name="решение")
    file = models.FileField("файл", upload_to=solution_upload_path, validators=[validate_solution_file])
    # Хранилище переименовывает файл при совпадении (reshenie_a1B2c3.pdf),
    # а участник должен видеть ровно то имя, с которым загружал.
    original_name = models.CharField("исходное имя", max_length=255, blank=True)

    class Meta:
        verbose_name = "файл решения"
        verbose_name_plural = "файлы решений"

    def __str__(self):
        return self.file.name

    def save(self, *args, **kwargs):
        if not self.original_name and self.file:
            self.original_name = Path(self.file.name).name[:255]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        # Решения не лежат в открытом /media/: адрес ведёт через проверку прав.
        return reverse("contest:submission_file", args=[self.pk])

    @property
    def filename(self):
        """Имя файла, как его загрузил участник, без служебного пути."""
        return self.original_name or Path(self.file.name).name


class Grade(TimeStampedModel):
    """Оценка за конкретную попытку. Проверяют организаторы."""

    class Status(models.TextChoices):
        NEW = "new", "Не проверено"
        IN_REVIEW = "in_review", "Проверяется"
        GRADED = "graded", "Проверено"

    submission = models.OneToOneField(Submission, on_delete=models.CASCADE,
                                      related_name="grade", verbose_name="решение")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="grades", verbose_name="проверяющий")
    score = models.DecimalField("балл", max_digits=6, decimal_places=2, null=True, blank=True)
    comment = models.TextField("комментарий проверяющего", blank=True,
                               help_text="Виден участнику после публикации результатов")
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.NEW)

    class Meta:
        verbose_name = "оценка"
        verbose_name_plural = "оценки"

    def __str__(self):
        return f"{self.submission} — {self.score if self.score is not None else '—'}"


class Score(TimeStampedModel):
    """
    Балл участника за задачу.

    Зачем отдельно от Grade: Grade привязан к загруженному решению, а на
    очной площадке участник ничего не загружает — он пишет на бумаге, и
    организатор просто вносит баллы. Score описывает результат независимо
    от того, откуда работа: с сайта или с площадки.

    Участник видит свои баллы не сразу, а только когда администратор
    опубликует результаты этапа (Stage.results_published) — иначе
    недописанная ведомость утекает раньше времени.
    """

    registration = models.ForeignKey(
        "participation.Registration", on_delete=models.CASCADE,
        related_name="scores", verbose_name="участие",
    )
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE,
                                related_name="scores", verbose_name="задача")
    points = models.DecimalField("балл", max_digits=6, decimal_places=2, null=True, blank=True,
                                 help_text="Пусто — задача не проверена или не сдавалась")
    venue = models.ForeignKey(
        "venues.Venue", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scores", verbose_name="площадка",
        help_text="Где писал участник. Пусто — сдавал дистанционно",
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="entered_scores", verbose_name="кто внёс",
    )

    class Meta:
        verbose_name = "балл за задачу"
        verbose_name_plural = "баллы за задачи"
        ordering = ["problem__number"]
        constraints = [
            models.UniqueConstraint(fields=["registration", "problem"],
                                    name="unique_score_per_problem"),
        ]

    def __str__(self):
        return f"{self.registration.user} — задача {self.problem.number}: {self.points if self.points is not None else '—'}"

"""
Контент сайта: новости, лекции, статические страницы, архив задач.

Архив — это не отдельные модели, а фильтр по сезону над теми же
таблицами. «Лекции этого года» и «архив лекций» — один шаблон.
"""

from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.content.embeds import detect_platform, embed_url, platform_title
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_upload_size
from apps.seasons.models import Season


class PublishedQuerySet(models.QuerySet):
    def published(self):
        return self.filter(is_published=True)


class News(TimeStampedModel):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="news",
                               null=True, blank=True, verbose_name="сезон")
    title = models.CharField("заголовок", max_length=250)
    slug = models.SlugField("адрес", unique=True)
    summary = models.CharField("краткое описание", max_length=400, blank=True)
    body = models.TextField("текст")
    cover = models.ImageField("картинка", upload_to="news/", blank=True)
    published_at = models.DateTimeField("дата публикации", default=timezone.now)
    is_published = models.BooleanField("опубликовано", default=False)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "новость"
        verbose_name_plural = "новости"
        ordering = ["-published_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("content:news_detail", args=[self.slug])


class LectureQuerySet(models.QuerySet):
    def published(self):
        """Лекции, которые видят участники: только одобренные."""
        return self.filter(status=Lecture.Status.APPROVED)

    def editable_by(self, user):
        """Лекции, которые человек вправе править: свои, а админу — все."""
        from apps.accounts.models import User

        if not user.is_authenticated:
            return self.none()
        if user.is_superuser or user.role == User.Role.ADMIN:
            return self.all()
        return self.filter(created_by=user)


class Lecture(TimeStampedModel):
    """
    Лекция подготовительного курса. Архив — это лекции прошлых сезонов.

    Путь тот же, что у задач: организатор добавляет запись и отправляет
    на одобрение, участники видят её только после того, как администратор
    одобрит. Ошибиться ссылкой легко, а лекция на главной странице
    раздела — лицо олимпиады.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PENDING = "pending", "На одобрении"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отклонена"

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="lectures", verbose_name="сезон")

    title = models.CharField("название", max_length=250)
    slug = models.SlugField("адрес")
    lecturer = models.CharField("лектор", max_length=150, blank=True)
    description = models.TextField("описание", blank=True)

    held_at = models.DateTimeField("дата проведения", null=True, blank=True)
    video_url = models.URLField(
        "ссылка на видео", blank=True,
        help_text="Ссылка на ОДНО видео: ВКонтакте, YouTube или Rutube — "
                  "скопируйте адрес из строки браузера, видео заиграет прямо на сайте. "
                  "Ссылка на плейлист не встраивается: для плейлистов есть отдельный раздел.",
    )
    slides = models.FileField("презентация", upload_to="lectures/", blank=True, validators=[validate_upload_size])
    cover = models.ImageField("превью", upload_to="lectures/covers/", blank=True)

    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.DRAFT)
    moderation_comment = models.TextField("комментарий администратора", blank=True,
                                          help_text="Виден автору, если лекция отклонена")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="authored_lectures", verbose_name="кто добавил",
    )

    objects = LectureQuerySet.as_manager()

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    @property
    def embed_url(self):
        """Адрес для проигрывателя на странице лекции, если видео встраивается."""
        return embed_url(self.video_url)

    @property
    def platform(self):
        return detect_platform(self.video_url)

    @property
    def platform_title(self):
        return platform_title(self.platform)

    def get_absolute_url(self):
        return reverse("content:lecture_detail", args=[self.season.slug, self.slug])

    class Meta:
        verbose_name = "лекция"
        verbose_name_plural = "лекции"
        ordering = ["-held_at"]
        constraints = [
            models.UniqueConstraint(fields=["season", "slug"], name="unique_lecture_slug_per_season"),
        ]

    def __str__(self):
        return self.title


class Page(TimeStampedModel):
    """Статическая страница: о олимпиаде, правила, контакты."""

    slug = models.SlugField("адрес", unique=True)
    title = models.CharField("заголовок", max_length=250)
    body = models.TextField("текст (HTML)")
    show_in_menu = models.BooleanField("показывать в меню", default=False)
    menu_order = models.PositiveSmallIntegerField("порядок в меню", default=100)
    is_published = models.BooleanField("опубликовано", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "страница"
        verbose_name_plural = "страницы"
        ordering = ["menu_order"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("content:page", args=[self.slug])


class ArchiveMaterial(TimeStampedModel):
    """
    Материал прошлых лет: условия тура целиком, разборы, данные к задачам, видео.

    Зачем отдельно от Problem: в архиве условия лежат общими PDF на весь тур,
    а не по задачам. Разрезать их на отдельные задачи — ручная работа, которую
    можно делать постепенно. ArchiveMaterial позволяет выложить архив сразу,
    как есть, а Problem заполнять по мере разбора.

    Файл хранится либо у нас (file), либо остаётся по внешней ссылке
    (external_url) — видео разборов весит гигабайты, и класть его в media
    незачем, для этого есть VK Видео и YouTube.
    """

    class Kind(models.TextChoices):
        PROBLEMS = "problems", "Условия задач"
        SOLUTIONS = "solutions", "Решения и разборы"
        DATA = "data", "Данные к задачам"
        CODE = "code", "Код и ноутбуки"
        VIDEO = "video", "Видеоразбор"
        RESULTS = "results", "Результаты"
        OTHER = "other", "Прочее"

    #: Порядок разделов на странице архива. Сначала то, ради чего туда
    #: заходят — условия и разборы; данные к задачам и код нужны реже,
    #: поэтому уходят вниз и не отодвигают главное.
    KIND_ORDER = {
        Kind.PROBLEMS: 1,
        Kind.SOLUTIONS: 2,
        Kind.VIDEO: 3,
        Kind.RESULTS: 4,
        Kind.DATA: 5,
        Kind.CODE: 6,
        Kind.OTHER: 7,
    }

    season = models.ForeignKey(Season, on_delete=models.CASCADE,
                               related_name="archive_materials", verbose_name="сезон")
    stage = models.ForeignKey("seasons.Stage", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="archive_materials", verbose_name="этап")

    kind = models.CharField("тип", max_length=12, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField("название", max_length=250)
    description = models.TextField("описание", blank=True)

    problem_number = models.PositiveSmallIntegerField(
        "номер задачи", null=True, blank=True,
        help_text="Если материал относится к одной задаче, а не ко всему туру",
    )

    file = models.FileField("файл", upload_to="archive/%Y/", blank=True,
                            validators=[validate_upload_size])
    external_url = models.URLField("внешняя ссылка", blank=True,
                                   help_text="Для больших файлов и видео: Яндекс.Диск, VK Видео")
    size_bytes = models.BigIntegerField("размер, байт", null=True, blank=True)

    source_path = models.CharField("путь в исходном архиве", max_length=500, blank=True,
                                   help_text="Заполняется при импорте, чтобы не задваивать материалы")

    order = models.PositiveSmallIntegerField("порядок", default=100)
    is_published = models.BooleanField("опубликовано", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "материал архива"
        verbose_name_plural = "материалы архива"
        ordering = ["-season__year", "order", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["season", "source_path"],
                condition=models.Q(source_path__gt=""),
                name="unique_archive_source_path",
            ),
        ]

    def __str__(self):
        return f"{self.season.year} — {self.title}"

    @property
    def url(self):
        """Ссылка на скачивание: свой файл или внешний источник."""
        if self.file:
            return self.file.url
        return self.external_url

    @property
    def is_hosted(self):
        """Файл лежит у нас, а не на Яндекс.Диске."""
        return bool(self.file)

    @property
    def size_display(self):
        if not self.size_bytes:
            return ""
        mb = self.size_bytes / 1024 / 1024
        return f"{mb:.0f} МБ" if mb >= 1 else f"{self.size_bytes / 1024:.0f} КБ"

    @property
    def extension(self) -> str:
        """Расширение файла: pdf, xlsx, ipynb…

        Берём из исходного пути, а не из названия: при импорте к имени
        файла Django может дописать суффикс от коллизий, а source_path
        хранит то, как файл назывался на диске.
        """
        source = self.source_path or self.file.name or self.external_url
        if not source:
            return ""
        return PurePosixPath(source.split("?")[0]).suffix.lstrip(".").lower()

    @property
    def display_name(self) -> str:
        """Название с расширением — по нему сразу видно, что скачаешь."""
        ext = self.extension
        if not ext or self.title.lower().endswith(f".{ext}"):
            return self.title
        return f"{self.title}.{ext}"


class Playlist(TimeStampedModel):
    """
    Плейлист с записями лекций целиком — на YouTube или во ВКонтакте.

    Отдельно от Lecture: плейлист это не одна лекция, а курс за сезон.
    Плеером плейлисты ВКонтакте не встраиваются, поэтому показываем их
    карточками со ссылкой, а не пытаемся проигрывать на сайте.
    """

    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="playlists",
        null=True, blank=True, verbose_name="сезон",
        help_text="Пусто — плейлист показывается во всех сезонах",
    )
    title = models.CharField("название", max_length=200)
    description = models.CharField("описание", max_length=300, blank=True)
    url = models.URLField("ссылка на плейлист")
    cover = models.ImageField(
        "превью", upload_to="playlists/", blank=True,
        help_text="Для YouTube подтягивается автоматически: manage.py fetch_playlist_covers",
    )
    order = models.PositiveSmallIntegerField("порядок", default=100)
    is_published = models.BooleanField("опубликован", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "плейлист"
        verbose_name_plural = "плейлисты"
        ordering = ["order", "title"]

    def __str__(self):
        return self.title

    @property
    def platform(self):
        return detect_platform(self.url)

    @property
    def platform_title(self):
        return platform_title(self.platform)

    @property
    def video_id(self):
        """Идентификатор ролика из ссылки — нужен, чтобы забрать превью."""
        from urllib.parse import parse_qs, urlparse

        if self.platform != "youtube":
            return ""
        parsed = urlparse(self.url)
        if "youtu.be" in (parsed.hostname or ""):
            return parsed.path.lstrip("/")
        return (parse_qs(parsed.query).get("v") or [""])[0]


class Photo(TimeStampedModel):
    """
    Фотография с очного тура или финала.

    Отдельная модель, а не картинки внутри текста страницы: снимки
    привязаны к году, их добавляют пачками после каждого финала, и
    подписи к ним нужны отдельно от текста.

    Хранятся у нас, а не ссылками на внешний альбом: альбомы переезжают
    и закрываются, а архив олимпиады должен пережить это.
    """

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="photos",
                               null=True, blank=True, verbose_name="сезон",
                               help_text="Год, с которого снимок. Пусто — без года")
    image = models.ImageField("фотография", upload_to="photos/%Y/",
                              validators=[validate_upload_size])
    caption = models.CharField("подпись", max_length=250, blank=True)
    order = models.PositiveSmallIntegerField("порядок", default=100)
    is_published = models.BooleanField("опубликовано", default=True)

    objects = PublishedQuerySet.as_manager()

    class Meta:
        verbose_name = "фотография"
        verbose_name_plural = "фотографии"
        # От первых сезонов к последним: галерея читается как история
        # олимпиады, а не как лента новостей.
        ordering = ["season__year", "order", "pk"]

    def __str__(self):
        return self.caption or f"Фото {self.pk}"

    @property
    def year_label(self) -> str:
        """Подпись года для галереи: «АО VI» или пусто.

        Берём последнее слово названия сезона — это римский номер.
        Полное название на карточке не помещается.
        """
        if not self.season:
            return ""
        return f"АО {self.season.title.split()[-1]}"

"""
Пользователи и роли.

Вход по e-mail (а не по логину) — школьнику проще запомнить почту.
Ролей три: участник, организатор, администратор. Отдельной роли «жюри»
нет — проверяют решения те же организаторы. Доступ организатора к
конкретной площадке определяется связью Venue.managers, а не ролью.
"""

import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Нужен e-mail")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        """Ролей три.

        Отдельного «жюри» нет намеренно: проверяет решения, ведёт площадку
        и отвечает за тур один и тот же человек — организатор. Что именно
        ему доступно, определяется правами Django (is_staff и группы),
        а не отдельной ролью.
        """

        PARTICIPANT = "participant", "Участник"
        ORGANIZER = "organizer", "Организатор"
        ADMIN = "admin", "Администратор"

    username = None
    email = models.EmailField("e-mail", unique=True)
    role = models.CharField("роль", max_length=20, choices=Role.choices, default=Role.PARTICIPANT)
    email_confirmed = models.BooleanField("e-mail подтверждён", default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    def __str__(self):
        return self.get_full_name() or self.email

    @property
    def is_participant(self):
        return self.role == self.Role.PARTICIPANT

    @property
    def is_organizer(self):
        return self.role == self.Role.ORGANIZER or self.managed_venues.exists()

    @property
    def is_manager(self):
        """Человек «с той стороны»: организатор или администратор.

        От этого зависит не только доступ, но и вид сайта: управляющий
        не регистрируется на площадки и не сдаёт решения — ему показывают
        инструменты, а не кнопки участника.
        """
        return self.role in (self.Role.ORGANIZER, self.Role.ADMIN) or self.is_superuser

    @property
    def is_admin(self):
        """Может одобрять задачи и публиковать результаты."""
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def latest_consent(self):
        return self.consents.order_by("-created_at").first()

    def participation_blockers(self):
        """Что мешает участвовать: список шагов, которые осталось сделать.

        Пустой список — можно записываться на площадку, сдавать решения
        и идти на второй тур. Для организаторов и администраторов не
        применяется: они не участвуют.
        """
        steps = []
        if not self.email_confirmed:
            steps.append("подтвердить почту по ссылке из письма")
        profile = getattr(self, "profile", None)
        if profile is None or not profile.is_complete:
            steps.append("заполнить анкету участника")
        consent = self.latest_consent
        if consent is None or not consent.grants_access:
            steps.append("загрузить подписанное согласие на обработку персональных данных")
        return steps

    @property
    def can_participate(self) -> bool:
        return self.is_participant and not self.participation_blockers()

    @property
    def can_review(self):
        """Допущен к проверке решений. Сейчас совпадает с is_manager,
        но право на конкретную задачу проверяет Problem.can_be_reviewed_by."""
        return self.is_manager


class ConsentMixin(models.Model):
    """Фиксация согласия на обработку персональных данных (152-ФЗ).

    Храним не только факт, но и дату с версией текста: если редакция
    согласия изменится, нужно понимать, на что именно человек соглашался.
    """

    consent_given = models.BooleanField("согласие на обработку ПД", default=False)
    consent_given_at = models.DateTimeField("дата согласия", null=True, blank=True)
    consent_version = models.CharField("версия текста согласия", max_length=20, blank=True)

    class Meta:
        abstract = True


class DocumentType(models.TextChoices):
    """Чем подтверждается личность.

    Паспорт есть не у всех: до 14 лет у школьника только свидетельство
    о рождении, а участники из-за рубежа приходят со своими документами.
    """

    PASSPORT_RF = "passport_rf", "Паспорт РФ"
    BIRTH_CERT = "birth_cert", "Свидетельство о рождении"
    FOREIGN = "foreign", "Документ другой страны"


#: У каких документов серия обязательна (у иностранных её может не быть).
DOC_TYPES_WITH_SERIES = (DocumentType.PASSPORT_RF, DocumentType.BIRTH_CERT)


class ParticipantProfile(ConsentMixin, TimeStampedModel):
    """
    Анкета школьника.

    Заполняется в два приёма. При регистрации — только почта и пароль
    (и подтверждение почты). Для участия (запись на площадку, сдача
    решений, второй тур) — полная анкета с документом и адресом: из неё
    собирается бланк согласия на обработку ПД, который школьник
    подписывает и загружает сканом. Если участнику нет 18, в анкете
    заполняются и данные законного представителя: согласие даёт он, и
    по 152-ФЗ его ФИО, документ и адрес должны быть в бланке. От руки
    в бланке только подписи — участника и представителя.

    Паспортные данные видят только администраторы (см. admin.py).
    Поля в базе необязательные: полноту проверяет форма и is_complete,
    иначе запись нельзя было бы создать в момент регистрации.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="пользователь")

    last_name = models.CharField("фамилия", max_length=100, blank=True)
    first_name = models.CharField("имя", max_length=100, blank=True)
    middle_name = models.CharField("отчество", max_length=100, blank=True)

    birth_date = models.DateField("дата рождения", null=True, blank=True)
    grade = models.PositiveSmallIntegerField("класс", null=True, blank=True)

    # Регион выбирается из списка (apps/accounts/regions.py), иначе в базе
    # заводятся «Москва», «г. Москва» и «МСК» как три разных региона.
    school = models.CharField("школа", max_length=250, blank=True)
    city = models.CharField("город", max_length=120, blank=True)
    region = models.CharField("регион", max_length=120, blank=True)

    phone = models.CharField("телефон", max_length=32, blank=True)
    telegram = models.CharField("Telegram", max_length=64, blank=True)

    # --- Документ и адрес участника (для согласия на обработку ПД) --------
    doc_type = models.CharField("документ", max_length=20, choices=DocumentType.choices, blank=True)
    doc_series = models.CharField("серия", max_length=20, blank=True)
    doc_number = models.CharField("номер", max_length=30, blank=True)
    doc_issued_at = models.DateField("дата выдачи", null=True, blank=True)
    doc_issued_by = models.CharField("кем выдан", max_length=300, blank=True)
    doc_division_code = models.CharField("код подразделения", max_length=7, blank=True,
                                         help_text="Только для паспорта РФ")
    reg_address = models.CharField("адрес регистрации", max_length=500, blank=True,
                                   help_text="Как в паспорте, с индексом")

    #: Без чего анкета участника не считается заполненной.
    # --- Законный представитель (если участнику нет 18) ------------------
    parent_last_name = models.CharField("фамилия представителя", max_length=100, blank=True)
    parent_first_name = models.CharField("имя представителя", max_length=100, blank=True)
    parent_middle_name = models.CharField("отчество представителя", max_length=100, blank=True)
    parent_doc_type = models.CharField("документ представителя", max_length=20,
                                       choices=DocumentType.choices, blank=True)
    parent_doc_series = models.CharField("серия (представитель)", max_length=20, blank=True)
    parent_doc_number = models.CharField("номер (представитель)", max_length=30, blank=True)
    parent_doc_issued_at = models.DateField("дата выдачи (представитель)", null=True, blank=True)
    parent_doc_issued_by = models.CharField("кем выдан (представитель)", max_length=300, blank=True)
    parent_doc_division_code = models.CharField("код подразделения (представитель)", max_length=7,
                                                blank=True)
    parent_reg_address = models.CharField("адрес регистрации (представитель)", max_length=500,
                                          blank=True)

    #: Серия не входит: у иностранных документов её бывает нет.
    REQUIRED_FIELDS = ("last_name", "first_name", "birth_date", "grade", "school", "city",
                       "region", "phone", "doc_type", "doc_number", "doc_issued_at",
                       "doc_issued_by", "reg_address")
    #: То же для представителя — только если участнику нет 18.
    PARENT_REQUIRED_FIELDS = ("parent_last_name", "parent_first_name", "parent_doc_type",
                              "parent_doc_number", "parent_doc_issued_at",
                              "parent_doc_issued_by", "parent_reg_address")
    #: Данные, которые попадают в бланк согласия. Если их поменять после
    #: загрузки скана, подписанное согласие перестаёт им соответствовать.
    CONSENT_FIELDS = ("last_name", "first_name", "middle_name", "birth_date",
                      "doc_type", "doc_series", "doc_number", "doc_issued_at",
                      "doc_issued_by", "doc_division_code", "reg_address",
                      "parent_last_name", "parent_first_name", "parent_middle_name",
                      "parent_doc_type", "parent_doc_series", "parent_doc_number",
                      "parent_doc_issued_at", "parent_doc_issued_by", "parent_doc_division_code",
                      "parent_reg_address")

    class Meta:
        verbose_name = "анкета участника"
        verbose_name_plural = "анкеты участников"

    def __str__(self):
        return self.full_name or self.user.email

    @property
    def full_name(self):
        return " ".join(filter(None, [self.last_name, self.first_name, self.middle_name]))

    @property
    def parent_full_name(self):
        return " ".join(filter(None, [self.parent_last_name, self.parent_first_name,
                                      self.parent_middle_name]))

    def age(self, on=None):
        if not self.birth_date:
            return None
        on = on or timezone.localdate()
        years = on.year - self.birth_date.year
        if (on.month, on.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    @property
    def is_minor(self) -> bool:
        """Нет 18 — согласие подписывает и законный представитель.

        Пока дата рождения не указана, считаем несовершеннолетним:
        школьников старше 18 почти не бывает, и лучше спросить лишнее.
        """
        age = self.age()
        return age is None or age < 18

    def missing_fields(self):
        """Названия незаполненных полей — чтобы показать, что осталось."""
        missing = [n for n in self.REQUIRED_FIELDS if not getattr(self, n)]
        if self.doc_type in DOC_TYPES_WITH_SERIES and not self.doc_series:
            missing.append("doc_series")
        if self.doc_type == DocumentType.PASSPORT_RF and not self.doc_division_code:
            missing.append("doc_division_code")
        if self.is_minor:
            missing += [n for n in self.PARENT_REQUIRED_FIELDS if not getattr(self, n)]
            if self.parent_doc_type in DOC_TYPES_WITH_SERIES and not self.parent_doc_series:
                missing.append("parent_doc_series")
            if self.parent_doc_type == DocumentType.PASSPORT_RF and not self.parent_doc_division_code:
                missing.append("parent_doc_division_code")
        return [self._meta.get_field(n).verbose_name for n in missing]

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()

    def consent_data(self):
        """Снимок данных, попавших в бланк согласия."""
        return {name: str(getattr(self, name) or "") for name in self.CONSENT_FIELDS}


def consent_upload_path(instance, filename):
    """Сканы согласий: в пути случайная папка, отдаются только через проверку прав."""
    return f"consents/user-{instance.user_id}/{secrets.token_urlsafe(12)}/{filename}"


class ConsentDocument(TimeStampedModel):
    """
    Скан подписанного согласия на обработку ПД.

    Школьник скачивает бланк (PDF из его анкеты), подписывает сам или
    вместе с родителем и загружает скан. С этого момента ему открыто
    участие, а администратор проверяет скан вручную: принимает или
    просит переслать — участнику уходит письмо с комментарием.

    Старые сканы не удаляются: при споре важно видеть, что и когда
    было прислано.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "На проверке"
        APPROVED = "approved", "Принято"
        REJECTED = "rejected", "Нужно переслать"
        # Участник поменял данные анкеты после загрузки: подписанный бланк
        # им больше не соответствует, нужен новый.
        OUTDATED = "outdated", "Устарело (данные изменены)"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="consents",
                             verbose_name="участник")
    file = models.FileField("скан", upload_to=consent_upload_path)
    original_name = models.CharField("исходное имя", max_length=255, blank=True)
    for_minor = models.BooleanField("согласие даёт представитель", default=True)
    data = models.JSONField("данные в бланке", default=dict, blank=True,
                            help_text="Что было в анкете в момент загрузки")
    status = models.CharField("статус", max_length=10, choices=Status.choices, default=Status.PENDING)
    review_comment = models.TextField(
        "комментарий участнику", blank=True,
        help_text="Если просите переслать — что не так. Уйдёт участнику письмом",
    )
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="проверил")
    reviewed_at = models.DateTimeField("когда проверено", null=True, blank=True)

    class Meta:
        verbose_name = "согласие на обработку ПД"
        verbose_name_plural = "согласия на обработку ПД"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.get_status_display()}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("accounts:consent_file", args=[self.pk])

    @property
    def filename(self):
        return self.original_name or self.file.name.rsplit("/", 1)[-1]

    @property
    def grants_access(self) -> bool:
        """Открывает ли этот скан участие.

        Да — сразу после загрузки: проверка ручная и занимает дни, а
        записаться на площадку нужно успеть. «Нужно переслать» доступ не
        отнимает: с участником связываются, и он досылает исправленное.
        Не открывает только устаревшее — там другие данные.
        """
        return self.status != self.Status.OUTDATED


class OrganizerProfile(TimeStampedModel):
    """
    Анкета организатора.

    Организаторы — свои люди: их заводит администратор вручную, поэтому
    достаточно почты и ФИО. Самостоятельной регистрации организаторов нет.
    Где человек проводит тур, видно из его площадок (Venue.managers).
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                related_name="organizer_profile", verbose_name="пользователь")

    last_name = models.CharField("фамилия", max_length=100)
    first_name = models.CharField("имя", max_length=100)
    middle_name = models.CharField("отчество", max_length=100, blank=True)

    phone = models.CharField("телефон", max_length=32, blank=True)
    telegram = models.CharField("Telegram", max_length=64, blank=True)

    class Meta:
        verbose_name = "анкета организатора"
        verbose_name_plural = "анкеты организаторов"

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return " ".join(filter(None, [self.last_name, self.first_name, self.middle_name]))

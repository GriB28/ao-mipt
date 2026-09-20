"""
Пользователи и роли.

Вход по e-mail (а не по логину) — школьнику проще запомнить почту.
Ролей три: участник, организатор, администратор. Отдельной роли «жюри»
нет — проверяют решения те же организаторы. Доступ организатора к
конкретной площадке определяется связью Venue.managers, а не ролью.
"""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

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


class ParticipantProfile(ConsentMixin, TimeStampedModel):
    """
    Анкета школьника. Персональные данные несовершеннолетних —
    храним минимум и фиксируем факт согласия (152-ФЗ).
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile", verbose_name="пользователь")

    last_name = models.CharField("фамилия", max_length=100)
    first_name = models.CharField("имя", max_length=100)
    middle_name = models.CharField("отчество", max_length=100, blank=True)

    birth_date = models.DateField("дата рождения", null=True, blank=True)
    grade = models.PositiveSmallIntegerField("класс", null=True, blank=True)

    # Школа, город и регион обязательны: по ним считают охват олимпиады
    # и раскладывают участников по площадкам. Регион выбирается из списка
    # (apps/accounts/regions.py), иначе в базе заводятся «Москва», «г. Москва»
    # и «МСК» как три разных региона.
    school = models.CharField("школа", max_length=250)
    city = models.CharField("город", max_length=120)
    region = models.CharField("регион", max_length=120)

    # Телефон или телеграм — хотя бы одно, проверяется в форме:
    # на уровне базы такое ограничение только мешало бы импорту.
    phone = models.CharField("телефон", max_length=32, blank=True)
    telegram = models.CharField("Telegram", max_length=64, blank=True)

    class Meta:
        verbose_name = "анкета участника"
        verbose_name_plural = "анкеты участников"

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return " ".join(filter(None, [self.last_name, self.first_name, self.middle_name]))


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

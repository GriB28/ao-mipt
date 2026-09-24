import re

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from apps.core.validators import validate_consent_file

from .models import OrganizerProfile, ParticipantProfile, User
from .regions import REGION_CHOICES

# Версия текста согласия. Меняется вместе с текстом на странице /page/consent/.
# Храним в профиле, чтобы знать, на какую именно редакцию человек согласился.
CONSENT_VERSION = "2026-09"


def consent_label() -> str:
    """Галочка согласия со ссылками на сами документы — иначе согласие ничтожно."""
    return mark_safe(
        'Я даю <a href="{consent}" target="_blank">согласие на обработку '
        "персональных данных</a> и принимаю "
        '<a href="{privacy}" target="_blank">политику обработки персональных данных</a>'.format(
            consent=reverse("content:page", args=["consent"]),
            privacy=reverse("content:page", args=["privacy"]),
        )
    )


class ContactRequiredMixin:
    """Телефон или телеграм — хотя бы одно.

    Почта есть всегда, но письма теряются и попадают в спам, а перед очным
    туром и финалом с участником надо связаться быстро. Требовать оба
    контакта избыточно, поэтому проверяем, что заполнен хотя бы один.
    """

    CONTACT_FIELDS = ("phone", "telegram")
    CONTACT_ERROR = "Укажите телефон или Telegram — хотя бы один способ связи."

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(name) for name in self.CONTACT_FIELDS):
            # Ошибку вешаем на оба поля, чтобы её было видно рядом с ними,
            # а не только общим сообщением наверху формы.
            for name in self.CONTACT_FIELDS:
                self.add_error(name, self.CONTACT_ERROR)
        return cleaned


class SignUpForm(UserCreationForm):
    """Регистрация школьника: только почта и пароль.

    Этого хватает, чтобы смотреть задачи и материалы. Анкету с документом
    и согласие на обработку ПД школьник заполняет позже в кабинете —
    они нужны для участия (см. User.participation_blockers).

    Организаторов здесь нет намеренно — это свои люди, их заводит
    администратор через админку (см. docs/admin-guide.md).
    """

    email = forms.EmailField(label="E-mail", help_text="На него придёт письмо для подтверждения")
    consent = forms.BooleanField(label="", label_suffix="")

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ссылки резолвятся во время создания формы, а не импорта модуля.
        self.fields["consent"].label = consent_label()
        # Стандартная подсказка Django к паролю — список из четырёх пунктов.
        # В форме-абзаце браузер выносит <ul> наружу из <p>, и на телефоне
        # он занимает полэкрана обычным шрифтом. Правила те же, короче.
        self.fields["password1"].help_text = (
            "Не короче 8 символов, не только цифры и не похож на e-mail."
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Пользователь с такой почтой уже зарегистрирован. "
                "Если это вы — войдите или восстановите пароль."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.role = User.Role.PARTICIPANT
        user.save()
        # Анкета заводится пустой: так в кабинете сразу есть что заполнять,
        # а факт согласия с политикой при регистрации фиксируется с датой.
        ParticipantProfile.objects.create(
            user=user, consent_given=True, consent_given_at=timezone.now(),
            consent_version=CONSENT_VERSION,
        )
        return user


DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ProfileForm(forms.ModelForm):
    """Полная анкета участника: из неё собирается бланк согласия.

    Блок представителя обязателен, только если по дате рождения участнику
    нет 18 — это проверяется здесь, на сервере; на странице блок
    показывается и прячется скриптом для удобства.
    """

    region = forms.ChoiceField(label="Регион", choices=[("", "— выберите регион —")] + [
        c for c in REGION_CHOICES if c[0]])

    class Meta:
        model = ParticipantProfile
        fields = [
            "last_name", "first_name", "middle_name", "birth_date",
            "doc_type", "doc_number", "doc_issued_at", "doc_issued_by", "reg_address",
            "grade", "school", "city", "region", "phone", "telegram",
            "parent_last_name", "parent_first_name", "parent_middle_name",
            "parent_doc_type", "parent_doc_number", "parent_doc_issued_at",
            "parent_doc_issued_by", "parent_reg_address",
        ]
        labels = {
            "parent_last_name": "Фамилия", "parent_first_name": "Имя",
            "parent_middle_name": "Отчество", "parent_doc_type": "Документ",
            "parent_doc_number": "Серия и номер", "parent_doc_issued_at": "Дата выдачи",
            "parent_doc_issued_by": "Кем выдан", "parent_reg_address": "Адрес регистрации",
            "doc_issued_by": "Кем выдан",
        }
        help_texts = {
            "doc_type": "До 14 лет — свидетельство о рождении",
            "doc_number": "Для паспорта РФ: 4 цифры серии и 6 цифр номера",
            "doc_issued_by": "Как написано в документе",
            "reg_address": "Как в паспорте, с индексом. Для свидетельства — адрес, где вы прописаны",
            "school": "Полное название, например: МБОУ «Лицей № 1»",
            "phone": "Для связи перед очным туром и финалом",
            "telegram": "Необязательно. Например: @ivanov",
            "parent_reg_address": "Как в паспорте, с индексом",
        }
        widgets = {
            "birth_date": DATE_WIDGET, "doc_issued_at": DATE_WIDGET,
            "parent_doc_issued_at": DATE_WIDGET,
            "reg_address": forms.Textarea(attrs={"rows": 2}),
            "parent_reg_address": forms.Textarea(attrs={"rows": 2}),
            "doc_issued_by": forms.Textarea(attrs={"rows": 2}),
            "parent_doc_issued_by": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
        }

    #: Поля представителя — группа, которую страница прячет для взрослых.
    PARENT_FIELDS = ParticipantProfile.PARENT_REQUIRED_FIELDS + ("parent_middle_name",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ParticipantProfile.REQUIRED_FIELDS:
            self.fields[name].required = True
        self.fields["grade"].widget.attrs.update({"min": 1, "max": 11})
        # Свидетельство о рождении бывает только у самого участника.
        self.fields["parent_doc_type"].choices = [
            c for c in self.fields["parent_doc_type"].choices if c[0] != "birth_cert"
        ]
        # Регион, записанный до появления списка, мог в него не попасть —
        # не выбрасываем анкету из-за этого, а добавляем значение в choices.
        current = self.instance.region if self.instance and self.instance.pk else ""
        if current and current not in dict(REGION_CHOICES):
            self.fields["region"].choices = list(self.fields["region"].choices) + [(current, current)]

    def participant_fields(self):
        return [self[n] for n in self.Meta.fields if n not in self.PARENT_FIELDS]

    def parent_fields(self):
        return [self[n] for n in self.Meta.fields if n in self.PARENT_FIELDS]

    def clean_grade(self):
        grade = self.cleaned_data.get("grade")
        if grade is not None and not 1 <= grade <= 11:
            raise forms.ValidationError("Класс — от 1 до 11.")
        return grade

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone and len(re.sub(r"\D", "", phone)) < 10:
            raise forms.ValidationError("Похоже, в номере не хватает цифр.")
        return phone

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()
        birth = cleaned.get("birth_date")
        if birth and not (today.year - 25 <= birth.year <= today.year - 6):
            self.add_error("birth_date", "Проверьте год рождения.")
        for prefix in ("", "parent_"):
            issued = cleaned.get(f"{prefix}doc_issued_at")
            if issued and issued > today:
                self.add_error(f"{prefix}doc_issued_at", "Дата выдачи не может быть в будущем.")
            if not prefix and issued and birth and issued < birth:
                self.add_error("doc_issued_at", "Документ не мог быть выдан раньше рождения.")
            self._normalize_passport(cleaned, prefix)

        # Представитель нужен, если участнику нет 18 (или дата не указана).
        probe = ParticipantProfile(birth_date=birth)
        if probe.is_minor:
            for name in ParticipantProfile.PARENT_REQUIRED_FIELDS:
                if not cleaned.get(name):
                    self.add_error(name, "Нужно, если участнику нет 18 лет.")
        return cleaned

    def _normalize_passport(self, cleaned, prefix):
        """Паспорт РФ: «1234 567890». Остальные документы — как ввели."""
        if cleaned.get(f"{prefix}doc_type") != "passport_rf":
            return
        number = cleaned.get(f"{prefix}doc_number") or ""
        digits = re.sub(r"\D", "", number)
        if number and len(digits) != 10:
            self.add_error(f"{prefix}doc_number", "У паспорта РФ 10 цифр: 4 — серия, 6 — номер.")
        elif digits:
            cleaned[f"{prefix}doc_number"] = f"{digits[:4]} {digits[4:]}"


class ConsentUploadForm(forms.Form):
    file = forms.FileField(label="Скан или фото подписанного согласия",
                           validators=[validate_consent_file])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        limit = settings.PARTICIPANT_UPLOAD_MAX_MB
        self.fields["file"].widget.attrs.update({"data-max-mb": f"{limit:g}",
                                                 "accept": ".pdf,.jpg,.jpeg,.png,image/*"})
        self.fields["file"].help_text = (
            f"PDF, JPG или PNG до {limit:g} МБ. Фото с телефона уменьшится автоматически."
        )


class OrganizerProfileForm(forms.ModelForm):
    class Meta:
        model = OrganizerProfile
        fields = ["last_name", "first_name", "middle_name", "phone", "telegram"]

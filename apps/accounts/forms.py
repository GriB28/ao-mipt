from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

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


class SignUpForm(ContactRequiredMixin, UserCreationForm):
    """Регистрация школьника.

    Организаторов здесь нет намеренно — это свои люди, их заводит
    администратор через админку (см. docs/admin-guide.md).
    """

    email = forms.EmailField(label="E-mail", help_text="На него придёт письмо для подтверждения")
    last_name = forms.CharField(label="Фамилия", max_length=100)
    first_name = forms.CharField(label="Имя", max_length=100)

    grade = forms.IntegerField(label="Класс", min_value=1, max_value=11)
    school = forms.CharField(label="Школа", max_length=250,
                             help_text="Полное название, например: МБОУ «Лицей № 1»")
    city = forms.CharField(label="Город", max_length=120)
    region = forms.ChoiceField(label="Регион", choices=REGION_CHOICES)

    phone = forms.CharField(label="Телефон", max_length=32, required=False,
                            help_text="Телефон или Telegram — заполните хотя бы одно")
    telegram = forms.CharField(label="Telegram", max_length=64, required=False,
                               help_text="Например: @ivanov")

    consent = forms.BooleanField(label="")

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ссылки резолвятся во время создания формы, а не импорта модуля.
        self.fields["consent"].label = consent_label()

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
        ParticipantProfile.objects.create(
            user=user,
            last_name=self.cleaned_data["last_name"],
            first_name=self.cleaned_data["first_name"],
            grade=self.cleaned_data["grade"],
            school=self.cleaned_data["school"],
            city=self.cleaned_data["city"],
            region=self.cleaned_data["region"],
            phone=self.cleaned_data.get("phone", ""),
            telegram=self.cleaned_data.get("telegram", ""),
            consent_given=True,
            consent_given_at=timezone.now(),
            consent_version=CONSENT_VERSION,
        )
        return user


class ProfileForm(ContactRequiredMixin, forms.ModelForm):
    """Анкета в кабинете. Требования те же, что и при регистрации."""

    region = forms.ChoiceField(label="Регион", choices=REGION_CHOICES)

    class Meta:
        model = ParticipantProfile
        fields = [
            "last_name", "first_name", "middle_name", "birth_date", "grade",
            "school", "city", "region", "phone", "telegram",
        ]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("school", "city", "grade"):
            self.fields[name].required = True
        # Регион, записанный до появления списка, мог в него не попасть —
        # не выбрасываем анкету из-за этого, а добавляем значение в choices.
        current = self.instance.region if self.instance and self.instance.pk else ""
        if current and current not in dict(REGION_CHOICES):
            self.fields["region"].choices = list(REGION_CHOICES) + [(current, current)]


class OrganizerProfileForm(forms.ModelForm):
    class Meta:
        model = OrganizerProfile
        fields = ["last_name", "first_name", "middle_name", "phone", "telegram"]

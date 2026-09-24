import re

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils import timezone

from apps.core.validators import validate_consent_file

from .models import DOC_TYPES_WITH_SERIES, DocumentType, OrganizerProfile, ParticipantProfile, User
from .regions import REGION_CHOICES


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

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Стандартная подсказка Django к паролю — список из четырёх пунктов.
        # В форме-абзаце браузер выносит <ul> наружу из <p>, и на телефоне
        # он занимает полэкрана обычным шрифтом. Правила те же, короче.
        self.fields["password1"].help_text = (
            "Не короче 8 символов, не только цифры и не похож на e-mail."
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        existing = User.objects.filter(email__iexact=email).first()
        # Регистрация с неподтверждённым адресом — обычно человек не нашёл
        # письмо и пробует снова. Письмо отправим повторно, но пароль
        # не меняем: иначе чужую свежую регистрацию мог бы «перехватить»
        # любой, кто знает адрес. Забыл пароль — есть восстановление.
        self.unconfirmed_user = None
        if existing and existing.is_participant and not existing.email_confirmed:
            self.unconfirmed_user = existing
        elif existing:
            raise forms.ValidationError(
                "Пользователь с такой почтой уже зарегистрирован. "
                "Если это вы — войдите или восстановите пароль."
            )
        return email

    def validate_unique(self):
        # Повтор неподтверждённой регистрации — не ошибка (см. clean_email):
        # новую учётку не создаём, а шлём письмо ещё раз.
        if not getattr(self, "unconfirmed_user", None):
            super().validate_unique()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.role = User.Role.PARTICIPANT
        user.save()
        # Анкета заводится пустой: так в кабинете сразу есть что заполнять.
        # Согласие на обработку ПД — не галочкой здесь, а подписанным
        # бланком, который загружается из кабинета.
        ParticipantProfile.objects.create(user=user)
        return user


class DayMonthYearWidget(forms.SelectDateWidget):
    """Дата тремя списками: число, месяц, год.

    Поле type=date в браузере с английской локалью показывает
    месяц/день/год, и школьники путают порядок. Три списка в привычном
    порядке и печатать ничего не нужно — на телефоне это нативный выбор.
    """

    def __init__(self, years):
        # Подписи Django принимает в порядке «год, месяц, день».
        super().__init__(years=years, empty_label=("год", "месяц", "число"))

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # Порядок SelectDateWidget берёт из формата локали; фиксируем
        # «число — месяц — год», чтобы не зависеть от настроек сервера.
        order = {"day": 0, "month": 1, "year": 2}
        context["widget"]["subwidgets"].sort(key=lambda w: order[w["name"].rsplit("_", 1)[-1]])
        return context


def _years(back, forward=0):
    this = timezone.localdate().year
    return list(range(this + forward, this - back - 1, -1))


class ProfileForm(forms.ModelForm):
    """Полная анкета участника: из неё собирается бланк согласия.

    Если участнику нет 18, заполняется и раздел законного представителя:
    согласие даёт он, и его данные попадают в бланк. Обязателен раздел
    только для несовершеннолетних — проверяется здесь, на сервере; на
    странице он прячется скриптом для взрослых.
    """

    region = forms.ChoiceField(label="Регион", choices=[("", "— выберите регион —")] + [
        c for c in REGION_CHOICES if c[0]])

    class Meta:
        model = ParticipantProfile
        fields = [
            "last_name", "first_name", "middle_name", "birth_date",
            "doc_type", "doc_series", "doc_number", "doc_issued_at", "doc_issued_by",
            "doc_division_code", "reg_address",
            "grade", "school", "city", "region", "phone", "telegram",
            "parent_last_name", "parent_first_name", "parent_middle_name",
            "parent_doc_type", "parent_doc_series", "parent_doc_number",
            "parent_doc_issued_at", "parent_doc_issued_by", "parent_doc_division_code",
            "parent_reg_address",
        ]
        labels = {
            "doc_issued_by": "Кем выдан",
            "parent_last_name": "Фамилия", "parent_first_name": "Имя",
            "parent_middle_name": "Отчество", "parent_doc_type": "Документ",
            "parent_doc_series": "Серия", "parent_doc_number": "Номер",
            "parent_doc_issued_at": "Дата выдачи", "parent_doc_issued_by": "Кем выдан",
            "parent_doc_division_code": "Код подразделения",
            "parent_reg_address": "Адрес регистрации по паспорту",
        }
        help_texts = {
            "doc_type": "До 14 лет — свидетельство о рождении",
            "doc_issued_by": "Как написано в документе",
            "doc_division_code": "Только для паспорта РФ, например 770-001",
            "parent_doc_division_code": "Только для паспорта РФ, например 770-001",
            "reg_address": "Как в паспорте, с индексом. Если паспорта ещё нет — адрес, "
                           "по которому вы зарегистрированы",
            "school": "Полное название, например: МБОУ «Лицей № 1»",
            "phone": "Для связи перед очным туром и финалом",
            "telegram": "Необязательно. Например: @ivanov",
            "parent_reg_address": "Как в паспорте, с индексом",
        }
        widgets = {
            "reg_address": forms.Textarea(attrs={"rows": 2}),
            "doc_issued_by": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
            "doc_series": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "4510"}),
            "doc_number": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "123456"}),
            "parent_reg_address": forms.Textarea(attrs={"rows": 2}),
            "parent_doc_issued_by": forms.Textarea(attrs={"rows": 2}),
            "parent_doc_series": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "4510"}),
            "parent_doc_number": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "123456"}),
            "doc_division_code": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "770-001",
                                                        "inputmode": "numeric"}),
            "parent_doc_division_code": forms.TextInput(attrs={"autocomplete": "off",
                                                               "placeholder": "770-001",
                                                               "inputmode": "numeric"}),
        }

    #: Группы полей — так они и показываются на странице.
    SECTIONS = (
        ("Участник", ("last_name", "first_name", "middle_name", "birth_date")),
        ("Документ, удостоверяющий личность",
         ("doc_type", "doc_series", "doc_number", "doc_issued_at", "doc_issued_by",
          "doc_division_code", "reg_address")),
        ("Учёба и связь", ("grade", "school", "city", "region", "phone", "telegram")),
        ("Родитель или законный представитель",
         ("parent_last_name", "parent_first_name", "parent_middle_name", "parent_doc_type",
          "parent_doc_series", "parent_doc_number", "parent_doc_issued_at",
          "parent_doc_issued_by", "parent_doc_division_code", "parent_reg_address")),
    )
    #: Раздел, который нужен только несовершеннолетним.
    PARENT_SECTION = "Родитель или законный представитель"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ParticipantProfile.REQUIRED_FIELDS:
            self.fields[name].required = True
        self.fields["birth_date"].widget = DayMonthYearWidget(years=_years(back=25, forward=-6))
        self.fields["doc_issued_at"].widget = DayMonthYearWidget(years=_years(back=25))
        self.fields["parent_doc_issued_at"].widget = DayMonthYearWidget(years=_years(back=60))
        self.fields["grade"].widget.attrs.update({"min": 1, "max": 11})
        self.fields["doc_type"].choices = [("", "— выберите документ —")] + DocumentType.choices
        # Свидетельство о рождении бывает только у самого участника.
        self.fields["parent_doc_type"].choices = [("", "— выберите документ —")] + [
            c for c in DocumentType.choices if c[0] != DocumentType.BIRTH_CERT]
        # Регион, записанный до появления списка, мог в него не попасть —
        # не выбрасываем анкету из-за этого, а добавляем значение в choices.
        current = self.instance.region if self.instance and self.instance.pk else ""
        if current and current not in dict(REGION_CHOICES):
            self.fields["region"].choices = list(self.fields["region"].choices) + [(current, current)]

    def sections(self):
        return [(title, [self[n] for n in names], title == self.PARENT_SECTION)
                for title, names in self.SECTIONS]

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
        birth = cleaned.get("birth_date")
        issued = cleaned.get("doc_issued_at")
        if issued and birth and issued < birth:
            self.add_error("doc_issued_at", "Документ не мог быть выдан раньше рождения.")
        self._check_document(cleaned, "")

        # Представитель нужен, если участнику нет 18 (или дата не указана).
        if ParticipantProfile(birth_date=birth).is_minor:
            for name in ParticipantProfile.PARENT_REQUIRED_FIELDS:
                if not cleaned.get(name) and name not in self.errors:
                    self.add_error(name, "Нужно, если участнику нет 18 лет.")
            self._check_document(cleaned, "parent_")
        return cleaned

    def _check_document(self, cleaned, prefix):
        """Серия и номер по виду документа: ловим опечатки, не мешаем редким случаям."""
        kind = cleaned.get(f"{prefix}doc_type")
        series = re.sub(r"\s+", "", cleaned.get(f"{prefix}doc_series") or "").upper()
        number = re.sub(r"\s+", "", cleaned.get(f"{prefix}doc_number") or "")
        issued = cleaned.get(f"{prefix}doc_issued_at")
        if issued and issued > timezone.localdate():
            self.add_error(f"{prefix}doc_issued_at", "Дата выдачи не может быть в будущем.")
        if kind == DocumentType.PASSPORT_RF:
            if series and not re.fullmatch(r"\d{4}", series):
                self.add_error(f"{prefix}doc_series", "Серия паспорта — 4 цифры.")
            if number and not re.fullmatch(r"\d{6}", number):
                self.add_error(f"{prefix}doc_number", "Номер паспорта — 6 цифр.")
        elif kind == DocumentType.BIRTH_CERT:
            # Серия свидетельства: римские цифры, дефис, две русские буквы — «IV-МЮ».
            series = series.replace("–", "-").replace("—", "-")
            if series and not re.fullmatch(r"[IVXLCА-ЯЁ1]+-?[А-ЯЁ]{2}", series):
                self.add_error(f"{prefix}doc_series", "Серия свидетельства выглядит так: IV-МЮ.")
            if number and not re.fullmatch(r"\d{6}", number):
                self.add_error(f"{prefix}doc_number", "Номер свидетельства — 6 цифр.")
        if kind in DOC_TYPES_WITH_SERIES and not series:
            self.add_error(f"{prefix}doc_series", "Обязательное поле.")
        cleaned[f"{prefix}doc_series"] = series
        cleaned[f"{prefix}doc_number"] = number

        # Код подразделения — только у паспорта РФ: «770-001».
        code_field = f"{prefix}doc_division_code"
        digits = re.sub(r"\D", "", cleaned.get(code_field) or "")
        if kind == DocumentType.PASSPORT_RF:
            if not digits:
                self.add_error(code_field, "Обязательное поле для паспорта РФ.")
            elif len(digits) != 6:
                self.add_error(code_field, "Код подразделения — 6 цифр, например 770-001.")
            cleaned[code_field] = f"{digits[:3]}-{digits[3:]}" if len(digits) == 6 else digits
        else:
            cleaned[code_field] = ""


class LoginForm(AuthenticationForm):
    """Вход. Участник без подтверждённой почты не входит.

    Без подтверждения нет кабинета: опечатка в адресе иначе всплыла бы
    только в апреле, когда не дошёл вызов на финал. Сотрудников это не
    касается — их заводит администратор.
    """

    error_messages = AuthenticationForm.error_messages | {
        "invalid_login": "Неверная почта или пароль.",
        "unconfirmed": "Почта ещё не подтверждена. Откройте ссылку из письма, которое мы "
                       "прислали при регистрации, — или запросите письмо ещё раз.",
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_participant and not user.email_confirmed:
            raise forms.ValidationError(self.error_messages["unconfirmed"], code="unconfirmed")


class ResendConfirmationForm(forms.Form):
    email = forms.EmailField(label="E-mail, указанный при регистрации")


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

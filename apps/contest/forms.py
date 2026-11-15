from decimal import Decimal
from pathlib import Path

from django import forms
from django.conf import settings

from apps.core.sanitize import clean_html
from apps.core.validators import validate_upload_size
from apps.seasons.models import Stage

from .models import Grade, Problem, ProblemAttachment, Submission
from .scoring import CANONICAL_DASH, format_points, is_dash


class DashScoreField(forms.DecimalField):
    widget = forms.TextInput

    def to_python(self, value):
        if is_dash(value):
            return Decimal("0")
        return super().to_python(value)

    def prepare_value(self, value):
        if is_dash(value):
            return CANONICAL_DASH
        if isinstance(value, Decimal):
            return format_points(value)
        return super().prepare_value(value)



class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Поле для загрузки нескольких файлов сразу (PDF + код, материалы)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            if self.required:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return []
        single = super().clean
        if isinstance(data, (list, tuple)):
            cleaned = [single(item, initial) for item in data if item]
            if not cleaned and self.required:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return cleaned
        return [single(data, initial)]


class SubmissionForm(forms.ModelForm):
    files = MultipleFileField(label="Файлы решения", required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Предел для браузера: он сожмёт фото и не даст отправить лишнее.
        limit = settings.PARTICIPANT_UPLOAD_MAX_MB
        self.fields["files"].widget.attrs["data-max-mb"] = f"{limit:g}"
        self.fields["files"].help_text = (
            f"До {limit:g} МБ на файл. Фото с телефона уменьшатся автоматически."
        )

    class Meta:
        model = Submission
        fields = ("answer", "comment")
        widgets = {"comment": forms.Textarea(attrs={"rows": 3})}


def _plain(number):
    """10.00 → «10», 7.50 → «7.5»: баллы без лишних нулей."""
    return f"{number.normalize():f}"


class GradeForm(forms.ModelForm):
    """Оценка решения организатором.

    Балл необязателен: бывает нужно отложить решение в «Проверяется»
    и вернуться к нему позже, не выставляя пока ничего.
    """

    score = DashScoreField(
        label="Балл",
        required=False,
        max_digits=6,
        decimal_places=2,
    )

    class Meta:
        model = Grade
        fields = ("score", "comment", "status")
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 4,
                                             "placeholder": "Что именно не зачтено — это увидит участник"}),
        }

    def __init__(self, *args, max_score=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_score = max_score
        if max_score is not None:
            self.fields["score"].help_text = f"Максимум за задачу: {_plain(max_score)}"
        if self.instance and self.instance.pk and getattr(self.instance, "is_dash", False):
            self.initial["score"] = CANONICAL_DASH

    def clean_score(self):
        score = self.cleaned_data.get("score")
        if score is None:
            return score
        if score < 0:
            raise forms.ValidationError("Балл не может быть отрицательным.")
        # Балл выше максимума почти всегда опечатка (например, 100 вместо 10)
        # и молча портит итоговую таблицу.
        if self.max_score is not None and score > self.max_score:
            raise forms.ValidationError(f"Больше максимума за задачу ({_plain(self.max_score)}).")
        return score

    def clean(self):
        cleaned_data = super().clean()
        raw_score = (
            self.data.get(self.add_prefix("score"))
            if hasattr(self, "add_prefix")
            else self.data.get("score")
        )
        if raw_score is None:
            raw_score = self.data.get("score")
        if is_dash(raw_score):
            self.cleaned_data["is_dash"] = True
        else:
            self.cleaned_data["is_dash"] = False
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if "is_dash" in self.cleaned_data:
            instance.is_dash = self.cleaned_data["is_dash"]
        if commit:
            instance.save()
        return instance


class ProblemForm(forms.ModelForm):
    """
    Заведение и правка задачи организатором.

    Статуса и проверяющих здесь нет намеренно: одобряет задачу и назначает
    дополнительных проверяющих администратор, а не автор.

    Условие — только текстом на странице: PDF не читается на телефоне и
    не ищется. Времени публикации тоже нет: все задачи этапа открываются
    разом в момент его начала (задаётся в админке). Разбор прикладывает
    администратор после тура.
    """

    attachments = MultipleFileField(
        label="Прикреплённые файлы",
        required=False,
        help_text=f"Любые файлы к задаче любого формата (рисунки, графики, данные в csv/txt, таблицы, код, архивы). До {settings.MAX_UPLOAD_SIZE_MB} МБ на файл. Можно выбрать несколько.",
    )

    class Meta:
        model = Problem
        fields = ("stage", "number", "title", "max_score", "statement_html", "figure", "figure_caption")
        widgets = {
            "max_score": forms.NumberInput(attrs={
                "min": "0",
                "step": "any",
                "placeholder": "10",
            }),
            "statement_html": forms.Textarea(attrs={
                "rows": 12,
                "placeholder": "Условие задачи. Формулы — в долларах: $v_0 = \\sqrt{2gh}$",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Только этапы текущего сезона и без тренировочной песочницы:
        # задачу прошлого сезона организатору заводить незачем, а в
        # песочницу её кладёт setup_site.
        self.fields["stage"].queryset = (self.fields["stage"].queryset
                                         .filter(is_practice=False, season__is_active=True))
        if "stage" in self.fields and not self.initial.get("stage") and not getattr(self.instance, "pk", None):
            online = self.fields["stage"].queryset.filter(kind=Stage.Kind.ONLINE).first()
            if online:
                self.initial["stage"] = online
        # В модели условие необязательно (у задач из архива бывает только
        # PDF), а организатор без текста условия задачу не заведёт.
        self.fields["statement_html"].required = True
        self.fields["statement_html"].error_messages["required"] = "Нужно условие задачи."
        limit = settings.MAX_UPLOAD_SIZE_MB
        self.fields["attachments"].widget.attrs["data-max-mb"] = f"{limit:g}"
        if self.instance and self.instance.pk and self.instance.max_score is not None:
            self.initial["max_score"] = _plain(self.instance.max_score)

    def clean_max_score(self):
        max_score = self.cleaned_data.get("max_score")
        if max_score is not None and max_score <= 0:
            raise forms.ValidationError("Максимальный балл должен быть больше нуля.")
        return max_score

    def clean_statement_html(self):
        # Храним уже очищенный текст: в базе не должно лежать то, что
        # опасно показывать (см. apps/core/sanitize.py).
        return clean_html(self.cleaned_data["statement_html"])

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        if not isinstance(files, (list, tuple)):
            files = [files]
        for f in files:
            validate_upload_size(f)
        return files

    def save_attachments(self, problem):
        files = self.cleaned_data.get("attachments") or []
        if not isinstance(files, (list, tuple)):
            files = [files]
        new_attachments = []
        for f in files:
            name = Path(getattr(f, "name", "") or "attachment").name[:255]
            att = ProblemAttachment(
                problem=problem,
                file=f,
                original_name=name,
                title=name[:200],
            )
            att.save()
            new_attachments.append(att)
        return new_attachments

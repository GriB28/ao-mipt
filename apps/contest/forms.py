from django import forms

from apps.core.sanitize import clean_html

from .models import Grade, Problem, Submission


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Поле для загрузки нескольких файлов сразу (PDF + код)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)]


class SubmissionForm(forms.ModelForm):
    files = MultipleFileField(label="Файлы решения", required=True)

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


class ProblemForm(forms.ModelForm):
    """
    Заведение и правка задачи организатором.

    Статуса и проверяющих здесь нет намеренно: одобряет задачу и назначает
    дополнительных проверяющих администратор, а не автор. Максимального
    балла тоже нет — участникам он не показывается, а шкалу удобнее
    уточнять уже при проверке.

    Условие — только текстом на странице: PDF не читается на телефоне и
    не ищется. Времени публикации тоже нет: все задачи этапа открываются
    разом в момент его начала (задаётся в админке). Разбор прикладывает
    администратор после тура.
    """

    class Meta:
        model = Problem
        fields = ("stage", "number", "title", "statement_html", "figure", "figure_caption")
        widgets = {
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
        # В модели условие необязательно (у задач из архива бывает только
        # PDF), а организатор без текста условия задачу не заведёт.
        self.fields["statement_html"].required = True
        self.fields["statement_html"].error_messages["required"] = "Нужно условие задачи."

    def clean_statement_html(self):
        # Храним уже очищенный текст: в базе не должно лежать то, что
        # опасно показывать (см. apps/core/sanitize.py).
        return clean_html(self.cleaned_data["statement_html"])

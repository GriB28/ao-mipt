from django import forms

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
            self.fields["score"].help_text = f"Максимум за задачу: {max_score:g}"

    def clean_score(self):
        score = self.cleaned_data.get("score")
        if score is None:
            return score
        if score < 0:
            raise forms.ValidationError("Балл не может быть отрицательным.")
        # Балл выше максимума почти всегда опечатка (например, 100 вместо 10)
        # и молча портит итоговую таблицу.
        if self.max_score is not None and score > self.max_score:
            raise forms.ValidationError(f"Больше максимума за задачу ({self.max_score:g}).")
        return score


class ProblemForm(forms.ModelForm):
    """
    Заведение и правка задачи организатором.

    Статуса и проверяющих здесь нет намеренно: одобряет задачу и назначает
    дополнительных проверяющих администратор, а не автор. Максимального
    балла тоже нет — участникам он не показывается, а шкалу удобнее
    уточнять уже при проверке.
    """

    class Meta:
        model = Problem
        fields = ("stage", "number", "title", "statement_html", "statement_pdf",
                  "figure", "figure_caption", "publish_at",
                  "solution_pdf", "solution_published_at")
        widgets = {
            "statement_html": forms.Textarea(attrs={
                "rows": 12,
                "placeholder": "Условие задачи. Формулы — в долларах: $v_0 = \\sqrt{2gh}$",
            }),
            "publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "solution_published_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Тренировочная песочница в списке этапов не нужна: туда задачи
        # заводит только seed_demo, вручную там делать нечего.
        self.fields["stage"].queryset = self.fields["stage"].queryset.filter(is_practice=False)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("statement_html") and not cleaned.get("statement_pdf"):
            raise forms.ValidationError(
                "Нужно условие: либо текстом на странице, либо файлом PDF."
            )
        return cleaned

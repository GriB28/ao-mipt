from django import forms
from django.utils.text import slugify

from apps.content.embeds import detect_platform, embed_url

from .models import Lecture


class LectureForm(forms.ModelForm):
    """
    Добавление лекции организатором.

    Статуса здесь нет: одобряет администратор. Адрес (slug) считается из
    названия — организатору незачем про него думать.
    """

    class Meta:
        model = Lecture
        fields = ("season", "title", "lecturer", "held_at", "video_url",
                  "description", "slides", "cover")
        widgets = {
            "held_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "video_url": forms.URLInput(attrs={
                "placeholder": "https://vkvideo.ru/video-17906_456239245",
            }),
        }

    def clean_video_url(self):
        url = (self.cleaned_data.get("video_url") or "").strip()
        if not url:
            return url
        if not detect_platform(url):
            raise forms.ValidationError(
                "Не узнаём эту площадку. Подходят ВКонтакте, YouTube и Rutube."
            )
        if not embed_url(url):
            # Чаще всего сюда попадает ссылка на плейлист: такой плеер
            # не встраивается, и на странице лекции будет пусто.
            raise forms.ValidationError(
                "Это ссылка на плейлист, а не на видео — проигрыватель из неё не "
                "соберётся. Откройте нужное видео и скопируйте адрес из строки браузера. "
                "Для плейлистов есть отдельный раздел в админке."
            )
        return url

    def clean(self):
        cleaned = super().clean()
        title = cleaned.get("title")
        season = cleaned.get("season")
        if title and season and not self.instance.slug:
            cleaned["slug"] = self._unique_slug(title, season)
        return cleaned

    def _unique_slug(self, title, season):
        """Адрес из названия. Русские буквы slugify выбрасывает, поэтому
        для названия целиком на кириллице берём запасной вариант."""
        base = slugify(title, allow_unicode=False) or "lecture"
        slug, number = base, 1
        while Lecture.objects.filter(season=season, slug=slug).exclude(pk=self.instance.pk).exists():
            number += 1
            slug = f"{base}-{number}"
        return slug

    def save(self, commit=True):
        lecture = super().save(commit=False)
        if not lecture.slug:
            lecture.slug = self.cleaned_data["slug"]
        if commit:
            lecture.save()
        return lecture

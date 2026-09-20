"""
Страницы этапов, которые не проводятся на нашем сайте.

Очный и дистанционный этапы живут в своих приложениях: у первого карта
площадок, у второго — задачи и приём решений. Второй тур идёт на чужой
платформе, а финал — на кампусе, поэтому им хватает страницы с описанием.

Тексты берутся из поля «описание» этапа и правятся в админке
(Сезоны → Этапы), а не в коде: содержание будет дописываться.
"""

from django.http import Http404
from django.shortcuts import render

from apps.content.models import Photo

from .models import Season, Stage


def _stage_or_404(slug):
    season = Season.objects.active()
    if not season:
        raise Http404("Активный сезон не настроен.")
    try:
        return season, season.stages.get(slug=slug, is_published=True)
    except Stage.DoesNotExist as exc:
        raise Http404("Этап не найден.") from exc


def second_round(request):
    """Второй тур: проходит с прокторингом на платформе МФТИ."""
    season, stage = _stage_or_404("otbor-2")
    return render(request, "seasons/second_round.html", {"season": season, "stage": stage})


def final(request):
    """Финал: описание прошлых лет и фотографии."""
    season, stage = _stage_or_404("final")
    photos = Photo.objects.published().select_related("season")
    return render(request, "seasons/final.html", {
        "season": season, "stage": stage, "photos": photos,
    })

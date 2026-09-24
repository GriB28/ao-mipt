from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.content.models import News
from apps.seasons.models import Season

# Как этап показывается на схеме: иконка, куда ведёт карточка и в какую
# из трёх вложенных областей попадает.
#
#   primary    — очный и дистанционный: два равнозначных формата первого отбора
#   qualifying — второй тур; вместе с primary образует весь отборочный тур
#   final      — заключительный тур
#
# Ключ — slug этапа из apps/seasons/schedule.py. Отдельной модели под это
# нет намеренно: четыре статических элемента, которые меняются раз в жизни,
# в базе держать незачем. Названия и даты при этом берутся из базы, чтобы
# не расходились с расписанием.
SCHEME = {
    "ochny":   {"icon": "school",  "url": "venues:map",           "group": "primary"},
    "otbor-1": {"icon": "laptop",  "url": "contest:problem_list",  "group": "primary"},
    "otbor-2": {"icon": "network", "url": "seasons:second_round",  "group": "qualifying"},
    "final":   {"icon": "campus",  "url": "seasons:final",         "group": "final"},
}


def scheme_stages(season):
    """Этапы для схемы, разложенные по группам.

    Возвращает словарь группа → список карточек. Этап, которого нет в
    SCHEME, на схему не попадает — например тренировочная песочница.
    """
    groups = {"primary": [], "qualifying": [], "final": []}
    if not season:
        return groups

    for stage in season.stages.real().filter(is_published=True).order_by("order", "starts_at"):
        card = SCHEME.get(stage.slug)
        if not card:
            continue
        groups[card["group"]].append({
            "stage": stage,
            "icon": card["icon"],
            "url_name": card["url"],
        })
    return groups


def stage_status(season):
    """
    Строка состояния под баннером: что происходит с олимпиадой прямо сейчас.

    Три случая: этап идёт, этап ещё впереди, всё закончилось. Первый
    важнее второго — если один тур идёт, а другой впереди, показываем
    идущий: у него есть дедлайн, и это то, что нужно человеку сейчас.
    """
    if not season:
        return None
    stages = season.stages.real().filter(is_published=True)
    now = timezone.now()

    running = stages.filter(starts_at__lte=now, ends_at__gte=now).order_by("ends_at").first()
    if running:
        return {"stage": running, "state": "running", "when": running.ends_at}

    upcoming = stages.filter(starts_at__gt=now).order_by("starts_at").first()
    if upcoming:
        return {"stage": upcoming, "state": "upcoming", "when": upcoming.starts_at}

    return None


def home(request):
    season = Season.objects.active()
    context = {
        "season": season,
        "scheme": scheme_stages(season),
        "news": News.objects.filter(is_published=True)[:3],
        "status": stage_status(season),
    }
    return render(request, "core/home.html", context)


def healthz(request):
    """Жив ли сайт: отвечает ли Django и доступна ли база.

    Дёргает Docker (healthcheck) и внешний мониторинг. Никаких данных
    не отдаёт, только «ok» или 503.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return HttpResponse("db unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")

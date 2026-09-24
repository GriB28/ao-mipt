from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.contest.models import Problem, Score
from apps.contest.scoring import total as total_points
from apps.participation.models import Registration, VenueBooking, VenueBookingError
from apps.seasons.models import Season, Stage

from .forms import VenueForm, VenueMailForm
from .models import Venue


def _offline_stage(season):
    """Очный тур, который показываем на вкладке.

    Очных этапов два — осенний отбор и финал. Пока идёт или предстоит
    осенний, показываем его; после него вкладка переключится на финал.
    """
    return Stage.objects.current_or_next(season, Stage.Kind.OFFLINE)


def _twin_stage(stage, kind):
    """Тот же тур в другом формате — см. contest.views._twin_stage."""
    if not stage:
        return None
    return (stage.season.stages.real()
            .filter(order=stage.order, kind=kind, is_published=True)
            .exclude(pk=stage.pk).first())


def _my_booking(user, stage):
    """Текущая запись пользователя на этот этап или None."""
    if not (user.is_authenticated and stage):
        return None
    return (VenueBooking.objects
            .filter(registration__user=user, stage=stage)
            .exclude(status=VenueBooking.Status.CANCELLED)
            .select_related("venue").first())


def venue_map(request):
    """Страница с картой площадок."""
    season = Season.objects.active()
    stage = _offline_stage(season)
    return render(request, "venues/map.html", {
        "season": season, "stage": stage,
        "my_booking": _my_booking(request.user, stage),
        "my_venues": Venue.objects.managed_by(request.user),
        "online_twin": _twin_stage(stage, Stage.Kind.ONLINE),
    })


def venues_geojson(request):
    """Данные для Leaflet. Отдаём только одобренные площадки."""
    season = Season.objects.active()
    stage = _offline_stage(season)
    venues = Venue.objects.public()
    if season:
        venues = venues.filter(seasons=season)
    return JsonResponse({
        "type": "FeatureCollection",
        "features": [v.as_geojson_feature(stage) for v in venues],
    })


def venue_detail(request, pk):
    venue = get_object_or_404(Venue.objects.public(), pk=pk)
    season = Season.objects.active()
    stage = _offline_stage(season)
    booking = _my_booking(request.user, stage)
    return render(request, "venues/detail.html", {
        "venue": venue, "season": season, "stage": stage,
        "my_booking": booking,
        "booked_here": bool(booking and booking.venue_id == venue.pk),
        "can_manage": Venue.objects.managed_by(request.user).filter(pk=venue.pk).exists(),
    })


@require_POST
@login_required
def book_venue(request, pk):
    """Записаться на площадку очного тура.

    Запись одна на этап: выбор другой площадки переносит запись,
    а не создаёт вторую (см. VenueBooking.book).
    """
    if request.user.is_manager:
        raise PermissionDenied("Организаторы на площадки не записываются.")
    venue = get_object_or_404(Venue.objects.public(), pk=pk)
    if not request.user.can_participate:
        messages.error(request, "Чтобы записаться на площадку, заполните анкету и загрузите "
                                "согласие на обработку персональных данных.")
        return redirect("accounts:profile")
    season = Season.objects.active()
    stage = _offline_stage(season)
    if not stage:
        messages.error(request, "Очный тур пока не объявлен.")
        return redirect("venues:map")

    # Участие в сезоне могло не появиться, если человек зарегистрировался
    # раньше, чем сезон стал активным, — заводим его здесь.
    registration, _ = Registration.objects.get_or_create(user=request.user, season=season)
    try:
        VenueBooking.book(registration, stage, venue)
    except VenueBookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Вы записаны на площадку «{venue.title}».")
    return redirect("venues:detail", pk=venue.pk)


@require_POST
@login_required
def cancel_booking(request, pk):
    """Отменить запись: планы меняются, а место на площадке ограничено."""
    venue = get_object_or_404(Venue, pk=pk)
    stage = _offline_stage(Season.objects.active())
    booking = _my_booking(request.user, stage)
    if booking and booking.venue_id == venue.pk:
        booking.status = VenueBooking.Status.CANCELLED
        booking.save(update_fields=["status"])
        messages.success(request, "Запись отменена.")
    return redirect("venues:detail", pk=venue.pk)


@login_required
def apply_venue(request):
    """
    Добавление площадки очного тура.

    Доступно только организаторам и администраторам: площадки заводят свои
    люди, самостоятельных заявок от внешних школ мы не принимаем.
    """
    if not (request.user.is_organizer or request.user.is_staff):
        raise PermissionDenied("Добавлять площадки могут только организаторы.")
    form = VenueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        venue = form.save(commit=False)
        venue.created_by = request.user
        venue.status = Venue.Status.PENDING
        venue.save()
        venue.managers.add(request.user)
        season = Season.objects.active()
        if season:
            venue.seasons.add(season)
        return redirect("venues:apply_done")
    return render(request, "venues/apply.html", {"form": form})


def apply_done(request):
    return render(request, "venues/apply_done.html")


# --- Ведомость площадки -----------------------------------------------------


def _managed_venue_or_403(user, pk):
    """Площадка, за которую отвечает этот человек. Чужие — закрыты."""
    venue = get_object_or_404(Venue, pk=pk)
    if not Venue.objects.managed_by(user).filter(pk=pk).exists():
        raise PermissionDenied("Это не ваша площадка.")
    return venue


def _venue_problems(stage):
    """Задачи тура, по которым выставляются баллы.

    Берём все одобренные, а не только опубликованные: ведомость заполняют
    после тура, когда задачи уже могли снять с публикации.
    """
    if not stage:
        return Problem.objects.none()
    return (Problem.objects
            .filter(stage=stage, status=Problem.Status.APPROVED)
            .order_by("number"))


@login_required
def venue_participants(request, pk):
    """
    Список записавшихся на площадку и ведомость баллов.

    Баллы вносятся прямо в таблице: одна строка — участник, один столбец —
    задача. Участник увидит их не сразу, а когда администратор опубликует
    результаты этапа.
    """
    venue = _managed_venue_or_403(request.user, pk)
    season = Season.objects.active()
    stage = _offline_stage(season)
    problems = list(_venue_problems(stage))

    bookings = (VenueBooking.objects
                .filter(venue=venue, stage=stage)
                .exclude(status=VenueBooking.Status.CANCELLED)
                .select_related("registration__user", "registration__user__profile")
                .order_by("registration__user__profile__last_name"))

    if request.method == "POST":
        saved = _save_scores(request, venue, bookings, problems)
        messages.success(request, f"Сохранено оценок: {saved}.")
        return redirect("venues:participants", pk=venue.pk)

    # Готовые баллы раскладываем по (участие, задача), чтобы шаблон
    # не делал запрос на каждую клетку таблицы.
    existing = {
        (score.registration_id, score.problem_id): score
        for score in Score.objects.filter(registration__bookings__venue=venue,
                                          problem__in=problems)
    }
    rows = []
    for booking in bookings:
        cells = [
            {
                "problem": problem,
                "name": f"score-{booking.registration_id}-{problem.pk}",
                "value": (existing.get((booking.registration_id, problem.pk)) or Score()).points,
            }
            for problem in problems
        ]
        rows.append({
            "booking": booking,
            "cells": cells,
            "total": total_points((c["problem"], c["value"]) for c in cells),
        })

    return render(request, "venues/participants.html", {
        "venue": venue, "stage": stage, "problems": problems, "rows": rows,
        "results_published": bool(stage and stage.results_published),
    })


def _save_scores(request, venue, bookings, problems):
    """Разобрать таблицу баллов из POST. Пустая клетка стирает балл."""
    saved = 0
    allowed = {b.registration_id for b in bookings}
    for problem in problems:
        for registration_id in allowed:
            raw = request.POST.get(f"score-{registration_id}-{problem.pk}", "").strip()
            if raw == "":
                Score.objects.filter(registration_id=registration_id, problem=problem).delete()
                continue
            try:
                points = Decimal(raw.replace(",", "."))
            except InvalidOperation:
                messages.error(request, f"«{raw}» — это не число, балл не сохранён.")
                continue
            Score.objects.update_or_create(
                registration_id=registration_id, problem=problem,
                defaults={"points": points, "venue": venue, "entered_by": request.user},
            )
            saved += 1
    return saved


@login_required
def venue_results(request, pk):
    """Итоговая таблица площадки: суммы по участникам, сверху лучшие."""
    venue = _managed_venue_or_403(request.user, pk)
    season = Season.objects.active()
    stage = _offline_stage(season)
    problems = list(_venue_problems(stage))

    bookings = (VenueBooking.objects
                .filter(venue=venue, stage=stage)
                .exclude(status=VenueBooking.Status.CANCELLED)
                .select_related("registration__user", "registration__user__profile"))

    scores = {}
    for score in Score.objects.filter(problem__in=problems,
                                      registration__in=[b.registration_id for b in bookings]):
        scores.setdefault(score.registration_id, {})[score.problem_id] = score.points

    rows = []
    for booking in bookings:
        by_problem = scores.get(booking.registration_id, {})
        values = [by_problem.get(p.pk) for p in problems]
        rows.append({
            "booking": booking,
            "values": values,
            "total": total_points(zip(problems, values, strict=True)),
        })
    rows.sort(key=lambda r: r["total"], reverse=True)

    return render(request, "venues/results.html", {
        "venue": venue, "stage": stage, "problems": problems, "rows": rows,
    })


@require_POST
@login_required
def publish_results(request, pk):
    """Открыть баллы участникам. Кнопка только у администратора."""
    venue = _managed_venue_or_403(request.user, pk)
    if not request.user.is_admin:
        raise PermissionDenied("Публиковать результаты может только администратор.")

    stage = _offline_stage(Season.objects.active())
    if stage:
        stage.results_published = not stage.results_published
        stage.save(update_fields=["results_published"])
        messages.success(request, "Результаты этапа опубликованы — участники видят свои баллы."
                         if stage.results_published else
                         "Результаты скрыты от участников.")
    return redirect("venues:participants", pk=venue.pk)


@login_required
def venue_edit(request, pk):
    """
    Правка своей площадки.

    Описание меняется чаще всего — «вход со двора», «сбор в 9:30» — и
    просить об этом администратора каждый раз бессмысленно. Статус при
    правке не сбрасывается: одобренная площадка не должна пропадать с
    карты из-за исправленной опечатки.
    """
    venue = _managed_venue_or_403(request.user, pk)
    form = VenueForm(request.POST or None, instance=venue)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Площадка обновлена.")
        return redirect("venues:detail", pk=venue.pk)
    return render(request, "venues/edit.html", {"form": form, "venue": venue})


@login_required
def venue_mail(request, pk):
    """
    Письмо участникам своей площадки.

    Идёт через тот же механизм, что и общие рассылки: на каждого
    получателя заводится запись об отправке, поэтому повторное нажатие
    не пошлёт письмо дважды, а видно, кому оно дошло.
    """
    from apps.mailing.models import Newsletter
    from apps.mailing.services import queue_newsletter, send_pending

    venue = _managed_venue_or_403(request.user, pk)
    form = VenueMailForm(request.POST or None)
    recipients = Newsletter(audience=Newsletter.Audience.VENUE_PARTICIPANTS,
                            venue=venue).get_recipients()

    if request.method == "POST" and form.is_valid():
        newsletter = Newsletter.objects.create(
            subject=form.cleaned_data["subject"],
            body=form.cleaned_data["body"],
            audience=Newsletter.Audience.VENUE_PARTICIPANTS,
            venue=venue,
            created_by=request.user,
        )
        count = queue_newsletter(newsletter)
        # Площадка — это десятки людей, а не тысячи: отправляем сразу,
        # не дожидаясь cron. Очередь при этом остаётся той же самой,
        # поэтому недоотправленное доберёт команда send_newsletters.
        stats = send_pending(limit=count)
        messages.success(
            request,
            f"Получателей: {count}. Отправлено: {stats['sent']}."
            + (f" Не доставлено: {stats['failed']}." if stats["failed"] else "")
        )
        return redirect("venues:participants", pk=venue.pk)

    return render(request, "venues/mail.html", {
        "venue": venue, "form": form, "recipients": recipients,
    })

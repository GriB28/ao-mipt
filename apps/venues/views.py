from datetime import date
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import time
from django.db import OperationalError

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.contest.models import Problem, Score
from apps.contest.scoring import total as total_points
from apps.core.files import protected_file_response
from apps.participation.models import Registration, VenueBooking, VenueBookingError
from apps.seasons.models import Season, Stage

from .export import generate_offline_grading_excel, generate_venue_participants_excel
from .forms import VenueForm, VenueMailForm
from .models import Venue


def _offline_stage(season):
    """Очный тур, который показываем на вкладке.

    Показываем текущий или последний начавшийся очный тур (чтобы после
    окончания тура ведомость, проверка и сканы оставались доступны),
    пока не начнётся следующий очный тур (финал).
    Если ещё ни один тур не начался — показываем ближайший предстоящий.
    """
    return Stage.objects.current_or_latest_started(season, Stage.Kind.OFFLINE)


def _twin_stage(stage, kind):
    """Тот же тур в другом формате — см. contest.views._twin_stage."""
    if not stage:
        return None
    return (
        stage.season.stages.real()
        .filter(order=stage.order, kind=kind, is_published=True)
        .exclude(pk=stage.pk)
        .first()
    )


def _my_booking(user, stage):
    """Текущая запись пользователя на этот этап или None."""
    if not (user.is_authenticated and stage):
        return None
    return (
        VenueBooking.objects.filter(registration__user=user, stage=stage)
        .exclude(status=VenueBooking.Status.CANCELLED)
        .select_related("venue")
        .first()
    )




def _get_participant_offline_results(user, stage, my_booking):
    """Результаты очного тура для участника: баллы по задачам своего комплекта и скан."""
    if not (user.is_authenticated and stage and my_booking and stage.results_published):
        return None

    active_variant = my_booking.effective_variant
    all_problems = _venue_problems(stage)

    # Задачи комплекта участника (или общие без комплекта)
    variant_problems = [
        p for p in all_problems
        if p.variant is None or p.variant == active_variant
    ]
    if not variant_problems and all_problems:
        variant_problems = all_problems

    scores_map = {
        s.problem_id: s
        for s in Score.objects.filter(
            registration=my_booking.registration,
            problem__in=variant_problems,
        )
    }

    items = []
    total = Decimal("0")
    for p in variant_problems:
        score_obj = scores_map.get(p.pk)
        pts = score_obj.points if (score_obj and not score_obj.is_skipped) else None
        if pts is not None:
            total += pts

        items.append({
            "problem": p,
            "score": score_obj,
            "points": pts,
            "points_display": _format_points(pts) if pts is not None else "0",
            "is_skipped": score_obj.is_skipped if score_obj else False,
        })

    scan_url = ""
    if my_booking.work_scan and my_booking.can_view_scan(user):
        scan_url = my_booking.get_scan_url()

    return {
        "booking": my_booking,
        "venue": my_booking.venue,
        "held_at": my_booking.effective_held_at,
        "variant": active_variant,
        "has_scan": bool(my_booking.work_scan),
        "scan_url": scan_url,
        "problems": items,
        "total": _format_points(total),
    }


def venue_map(request):
    """Страница очного тура: карта площадок, проверка задач и загрузка сканов."""
    season = Season.objects.active()
    stage = _offline_stage(season)

    tab = request.GET.get("tab", "map")
    if not (request.user.is_authenticated and request.user.is_manager):
        tab = "map"

    my_booking = _my_booking(request.user, stage)

    context = {
        "season": season,
        "stage": stage,
        "my_booking": my_booking,
        "my_venues": Venue.objects.managed_by(request.user),
        "online_twin": _twin_stage(stage, Stage.Kind.ONLINE),
        "tab": tab,
        "now": timezone.now(),
        "my_results": _get_participant_offline_results(request.user, stage, my_booking),
    }

    if tab == "grading":
        context.update(_get_grading_context(request, season, stage))
        if request.method == "POST":
            saved = _save_all_offline_scores(request, context["bookings"], context["problems"])
            messages.success(request, f"Сохранено оценок и данных: {saved}.")
            venue_arg = f"&venue={request.GET.get('venue')}" if request.GET.get('venue') else ""
            return redirect(f"{reverse('venues:map')}?tab=grading{venue_arg}")

    elif tab == "scans":
        context.update(_get_scans_context(request, season, stage))

    return render(request, "venues/map.html", context)


def venues_geojson(request):
    """Данные для Leaflet. Отдаём только одобренные площадки."""
    season = Season.objects.active()
    stage = _offline_stage(season)
    venues = Venue.objects.public()
    if season:
        venues = venues.filter(seasons=season)
    return JsonResponse(
        {
            "type": "FeatureCollection",
            "features": [v.as_geojson_feature(stage) for v in venues],
        }
    )


def venue_detail(request, pk):
    venue = get_object_or_404(Venue.objects.public(), pk=pk)
    season = Season.objects.active()
    stage = _offline_stage(season)
    booking = _my_booking(request.user, stage)
    return render(
        request,
        "venues/detail.html",
        {
            "venue": venue,
            "season": season,
            "stage": stage,
            "my_booking": booking,
            "booked_here": bool(booking and booking.venue_id == venue.pk),
            "can_manage": Venue.objects.managed_by(request.user).filter(pk=venue.pk).exists(),
        },
    )


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
    if venue.registration_closed:
        messages.error(request, "Запись на эту площадку заблокирована организаторами.")
        return redirect("venues:detail", pk=venue.pk)
    if venue.stage_passed:
        messages.error(request, "Запись на эту площадку закрыта: очный этап уже прошёл.")
        return redirect("venues:detail", pk=venue.pk)
    if not request.user.can_participate:
        messages.error(
            request,
            "Чтобы записаться на площадку, заполните анкету и загрузите "
            "согласие на обработку персональных данных.",
        )
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
        if not booking.can_cancel:
            messages.error(request, "Нельзя отменить запись: очный этап уже прошёл.")
            return redirect("venues:detail", pk=venue.pk)
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

    Берём все одобренные, сортируем по натуральному ключу (1.1, 1.2, 2.1...).
    """
    if not stage:
        return []
    problems = list(Problem.objects.filter(stage=stage, status=Problem.Status.APPROVED))
    problems.sort(key=lambda p: p.sort_key)
    return problems


def _format_points(val):
    if val is None:
        return ""
    return str(int(val)) if val == val.to_integral() else f"{val:.2f}".rstrip("0").rstrip(".")


def _get_grading_context(request, season, stage):
    all_venues = Venue.objects.public()
    if season:
        all_venues = all_venues.filter(seasons=season).order_by("city", "short_title", "title")

    problems = _venue_problems(stage)
    for p in problems:
        p.max_score_plain = _format_points(p.max_score) if p.max_score is not None else ""

    bookings = (
        VenueBooking.objects.filter(stage=stage)
        .exclude(status=VenueBooking.Status.CANCELLED)
        .select_related("registration__user", "registration__user__profile", "venue")
    )
    selected_venue_id = request.GET.get("venue", "").strip()
    if selected_venue_id and selected_venue_id.isdigit():
        bookings = bookings.filter(venue_id=int(selected_venue_id))

    search_query = request.GET.get("q", "").strip()
    if search_query:
        query_lower = search_query.lower()
        filtered = []
        for b in bookings:
            user = b.registration.user
            profile = getattr(user, "profile", None)
            full_name = profile.full_name.lower() if profile and profile.full_name else ""
            v_short = (b.venue.short_title or "").lower()
            v_full = (b.venue.title or "").lower()
            if (
                query_lower in full_name
                or query_lower in user.email.lower()
                or query_lower in b.venue.city.lower()
                or query_lower in v_short
                or query_lower in v_full
            ):
                filtered.append(b)
        bookings = filtered
    else:
        bookings = bookings.order_by(
            "venue__city",
            "venue__short_title",
            "venue__title",
            "registration__user__profile__last_name",
            "registration__user__email",
        )

    existing_scores = {
        (s.registration_id, s.problem_id): s
        for s in Score.objects.filter(registration__bookings__stage=stage, problem__in=problems)
    }

    rows = []
    for booking in bookings:
        active_variant = booking.effective_variant
        held_at_val = (
            booking.held_at.strftime("%Y-%m-%d")
            if booking.held_at
            else (booking.venue.event_date.strftime("%Y-%m-%d") if booking.venue and booking.venue.event_date else "")
        )
        cells = []
        row_total = Decimal("0")
        for problem in problems:
            is_inactive = problem.variant is not None and problem.variant != active_variant
            score_obj = existing_scores.get((booking.registration_id, problem.pk))
            val = score_obj.points if score_obj else None
            if not is_inactive and val is not None:
                row_total += val

            val_str = _format_points(val)

            cells.append({
                "problem": problem,
                "name": f"score_{booking.pk}_{problem.pk}",
                "value": val_str,
                "is_inactive": is_inactive,
                "is_skipped": score_obj.is_skipped if score_obj else is_inactive,
                "max_score": _format_points(problem.max_score) if problem.max_score is not None else "",
            })

        total_str = _format_points(row_total)

        rows.append({
            "booking": booking,
            "held_at_val": held_at_val,
            "variant": active_variant,
            "cells": cells,
            "total": total_str,
            "work_scan_url": booking.get_scan_url() if booking.work_scan else "",
            "has_scan": bool(booking.work_scan),
        })

    return {
        "all_venues": all_venues,
        "selected_venue_id": selected_venue_id,
        "search_query": search_query,
        "problems": problems,
        "bookings": bookings,
        "rows": rows,
    }


def _save_all_offline_scores(request, bookings, problems):
    saved = 0
    allowed_bookings = {b.id: b for b in bookings}
    for booking_id, booking in allowed_bookings.items():
        raw_held_at = request.POST.get(f"held_at_{booking_id}")
        if raw_held_at is not None:
            raw_held_at = raw_held_at.strip()
            booking.held_at = raw_held_at if raw_held_at else None
            booking.save(update_fields=["held_at"])

        raw_variant = request.POST.get(f"variant_{booking_id}")
        if raw_variant is not None and raw_variant.strip().isdigit():
            v = int(raw_variant.strip())
            if v in (1, 2):
                booking.variant = v
                booking.save(update_fields=["variant"])

        for problem in problems:
            key = f"score_{booking_id}_{problem.pk}"
            raw = request.POST.get(key)
            if raw is None:
                continue
            raw = raw.strip()
            if raw == "":
                Score.objects.filter(registration=booking.registration, problem=problem).delete()
                continue
            try:
                points = Decimal(raw.replace(",", "."))
            except InvalidOperation:
                continue
            if points < 0 or (problem.max_score is not None and points > problem.max_score):
                continue
            is_skipped = problem.variant is not None and problem.variant != booking.effective_variant
            Score.objects.update_or_create(
                registration=booking.registration,
                problem=problem,
                defaults={
                    "points": points,
                    "venue": booking.venue,
                    "entered_by": request.user,
                    "is_skipped": is_skipped,
                },
            )
            saved += 1
    return saved


def _get_scans_context(request, season, stage):
    all_venues = Venue.objects.public()
    if season:
        all_venues = all_venues.filter(seasons=season).order_by("city", "short_title", "title")

    bookings = (
        VenueBooking.objects.filter(stage=stage)
        .exclude(status=VenueBooking.Status.CANCELLED)
        .select_related("registration__user", "registration__user__profile", "venue")
        .order_by(
            "registration__user__profile__last_name",
            "registration__user__profile__first_name",
            "registration__user__email",
        )
    )
    selected_venue_id = request.GET.get("venue", "").strip()
    if selected_venue_id and selected_venue_id.isdigit():
        bookings = bookings.filter(venue_id=int(selected_venue_id))

    search_query = request.GET.get("q", "").strip()

    participants_list = []
    for b in bookings:
        user = b.registration.user
        profile = getattr(user, "profile", None)
        full_name = profile.full_name if profile and profile.full_name else user.email
        if search_query:
            q_lower = search_query.lower()
            v_short = (b.venue.short_title or "").lower()
            v_full = (b.venue.title or "").lower()
            if (
                q_lower not in full_name.lower()
                and q_lower not in user.email.lower()
                and q_lower not in b.venue.city.lower()
                and q_lower not in v_short
                and q_lower not in v_full
            ):
                continue
        held_at_val = (
            b.held_at.strftime("%Y-%m-%d")
            if b.held_at
            else (b.venue.event_date.strftime("%Y-%m-%d") if b.venue and b.venue.event_date else "")
        )
        participants_list.append({
            "booking": b,
            "id": b.pk,
            "name": full_name,
            "email": user.email,
            "venue_title": b.venue.short_title or b.venue.title,
            "venue_full_title": b.venue.title,
            "venue_city": b.venue.city,
            "has_scan": bool(b.work_scan),
            "scan_url": b.get_scan_url(),
            "held_at": held_at_val,
            "variant": b.effective_variant,
        })

    return {
        "all_venues": all_venues,
        "selected_venue_id": selected_venue_id,
        "search_query": search_query,
        "participants_list": participants_list,
        "no_scan_count": sum(1 for p in participants_list if not p["has_scan"]),
        "has_scan_count": sum(1 for p in participants_list if p["has_scan"]),
    }


def _retry_on_db_lock(func, max_attempts=4):
    """Повторяет операцию при временной блокировке SQLite базы данных."""
    for attempt in range(max_attempts):
        try:
            return func()
        except OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < max_attempts - 1:
                time.sleep(0.15 * (attempt + 1))
            else:
                raise


@require_POST
@login_required
def offline_save_scores(request):
    """AJAX-сохранение балла, даты или комплекта очного тура."""
    if not request.user.is_manager:
        return JsonResponse({"error": "Forbidden"}, status=403)

    if request.content_type == "application/json":
        data = json.loads(request.body)
    else:
        data = request.POST

    booking_id = data.get("booking_id")
    if not booking_id:
        return JsonResponse({"error": "No booking_id"}, status=400)

    booking = get_object_or_404(
        VenueBooking.objects.select_related("registration", "stage", "venue"),
        pk=booking_id,
    )

    if "held_at" in data:
        raw_date = str(data.get("held_at") or "").strip()
        booking.held_at = raw_date if raw_date else None
        _retry_on_db_lock(lambda: booking.save(update_fields=["held_at"]))

    if "variant" in data:
        raw_v = str(data.get("variant") or "").strip()
        if raw_v in ("1", "2"):
            booking.variant = int(raw_v)
            _retry_on_db_lock(lambda: booking.save(update_fields=["variant"]))
            scores = Score.objects.filter(registration=booking.registration, problem__stage=booking.stage).select_related("problem")
            for s in scores:
                should_skip = s.problem.variant is not None and s.problem.variant != booking.effective_variant
                if s.is_skipped != should_skip:
                    s.is_skipped = should_skip
                    _retry_on_db_lock(lambda s=s: s.save(update_fields=["is_skipped"]))

    problem_id = data.get("problem_id")
    if problem_id:
        problem = get_object_or_404(Problem, pk=problem_id)
        raw_points = str(data.get("points") if data.get("points") is not None else "").strip()
        if raw_points == "":
            _retry_on_db_lock(lambda: Score.objects.filter(registration=booking.registration, problem=problem).delete())
        else:
            try:
                points = Decimal(raw_points.replace(",", "."))
            except InvalidOperation:
                return JsonResponse({"error": "Invalid number"}, status=400)
            if points < 0:
                return JsonResponse({"error": "Балл не может быть отрицательным."}, status=400)
            if problem.max_score is not None and points > problem.max_score:
                max_str = _format_points(problem.max_score)
                return JsonResponse(
                    {"error": f"Балл не может превышать максимум за задачу ({max_str})."},
                    status=400,
                )
            is_skipped = problem.variant is not None and problem.variant != booking.effective_variant
            _retry_on_db_lock(
                lambda: Score.objects.update_or_create(
                    registration=booking.registration,
                    problem=problem,
                    defaults={
                        "points": points,
                        "venue": booking.venue,
                        "entered_by": request.user,
                        "is_skipped": is_skipped,
                    },
                )
            )

    active_variant = booking.effective_variant
    scores = Score.objects.filter(registration=booking.registration, problem__stage=booking.stage).select_related("problem")
    total = Decimal("0")
    for s in scores:
        if s.points is not None:
            p_var = s.problem.variant
            if p_var is None or p_var == active_variant:
                total += s.points

    total_str = _format_points(total)

    return JsonResponse({
        "status": "ok",
        "total": total_str,
        "variant": active_variant,
    })


@require_POST
@login_required
def upload_offline_work_scan(request, pk=None):
    if not request.user.is_manager:
        raise PermissionDenied("Доступно только организаторам.")

    booking_id = pk or request.POST.get("booking_id")
    booking = get_object_or_404(
        VenueBooking.objects.select_related("registration__user", "stage", "venue"),
        pk=booking_id,
    )

    scan_file = request.FILES.get("work_scan")
    if not scan_file:
        messages.error(request, "Файл не выбран.")
        return redirect(f"{reverse('venues:map')}?tab=scans")

    ext = Path(scan_file.name).suffix.lower()
    if ext != ".pdf":
        messages.error(request, "Скан работы должен быть файлом в формате PDF (.pdf).")
        return redirect(f"{reverse('venues:map')}?tab=scans")

    limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if scan_file.size > limit:
        messages.error(request, f"Файл больше {settings.MAX_UPLOAD_SIZE_MB} МБ.")
        return redirect(f"{reverse('venues:map')}?tab=scans")

    if booking.work_scan:
        booking.work_scan.delete(save=False)
    booking.work_scan = scan_file

    if request.POST.get("variant") in ("1", "2"):
        booking.variant = int(request.POST.get("variant"))
    if request.POST.get("held_at"):
        booking.held_at = request.POST.get("held_at").strip() or None

    booking.save()
    messages.success(
        request,
        f"Скан работы для {booking.registration.user.get_full_name() or booking.registration.user.email} успешно сохранён.",
    )

    venue_arg = f"&venue={booking.venue_id}" if request.POST.get("from_venue") else ""
    return redirect(f"{reverse('venues:map')}?tab=scans{venue_arg}")


@require_POST
@login_required
def delete_offline_work_scan(request, pk):
    if not request.user.is_manager:
        raise PermissionDenied("Доступно только организаторам.")

    booking = get_object_or_404(VenueBooking, pk=pk)
    if booking.work_scan:
        booking.work_scan.delete(save=False)
        booking.work_scan = ""
        booking.save(update_fields=["work_scan"])
        messages.success(request, "Скан работы удалён.")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"status": "ok"})
    return redirect(f"{reverse('venues:map')}?tab=scans")


@login_required
def offline_work_scan(request, pk):
    booking = get_object_or_404(
        VenueBooking.objects.select_related("stage", "registration__user"), pk=pk
    )
    if not booking.can_view_scan(request.user) or not booking.work_scan:
        raise Http404

    user = booking.registration.user
    filename = f"scan_{user.get_full_name() or user.id}.pdf"
    return protected_file_response(request, booking.work_scan, filename)


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

    bookings = (
        VenueBooking.objects.filter(venue=venue, stage=stage)
        .exclude(status=VenueBooking.Status.CANCELLED)
        .select_related("registration__user", "registration__user__profile")
        .order_by("registration__user__profile__last_name")
    )

    if request.method == "POST":
        saved = _save_scores(request, venue, bookings, problems)
        messages.success(request, f"Сохранено оценок: {saved}.")
        return redirect("venues:participants", pk=venue.pk)

    # Готовые баллы раскладываем по (участие, задача), чтобы шаблон
    # не делал запрос на каждую клетку таблицы.
    existing = {
        (score.registration_id, score.problem_id): score
        for score in Score.objects.filter(registration__bookings__venue=venue, problem__in=problems)
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
        rows.append(
            {
                "booking": booking,
                "cells": cells,
                "total": total_points((c["problem"], c["value"]) for c in cells),
            }
        )

    return render(
        request,
        "venues/participants.html",
        {
            "venue": venue,
            "stage": stage,
            "problems": problems,
            "rows": rows,
            "results_published": bool(stage and stage.results_published),
        },
    )


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
            if points < 0:
                messages.error(request, "Балл не может быть отрицательным.")
                continue
            if problem.max_score is not None and points > problem.max_score:
                messages.error(
                    request,
                    f"Балл {points} за задачу {problem.number} превышает максимум ({_format_points(problem.max_score)})."
                )
                continue
            Score.objects.update_or_create(
                registration_id=registration_id,
                problem=problem,
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

    bookings = (
        VenueBooking.objects.filter(venue=venue, stage=stage)
        .exclude(status=VenueBooking.Status.CANCELLED)
        .select_related("registration__user", "registration__user__profile")
    )

    scores = {}
    for score in Score.objects.filter(
        problem__in=problems, registration__in=[b.registration_id for b in bookings]
    ):
        scores.setdefault(score.registration_id, {})[score.problem_id] = score.points

    rows = []
    for booking in bookings:
        by_problem = scores.get(booking.registration_id, {})
        values = [by_problem.get(p.pk) for p in problems]
        rows.append(
            {
                "booking": booking,
                "values": values,
                "total": total_points(zip(problems, values, strict=True)),
            }
        )
    rows.sort(key=lambda r: r["total"], reverse=True)

    return render(
        request,
        "venues/results.html",
        {
            "venue": venue,
            "stage": stage,
            "problems": problems,
            "rows": rows,
        },
    )


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
        messages.success(
            request,
            "Результаты этапа опубликованы — участники видят свои баллы."
            if stage.results_published
            else "Результаты скрыты от участников.",
        )
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
    recipients = Newsletter(audience=Newsletter.Audience.VENUE_PARTICIPANTS, venue=venue).get_recipients()

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
            + (f" Не доставлено: {stats['failed']}." if stats["failed"] else ""),
        )
        return redirect("venues:participants", pk=venue.pk)

    return render(
        request,
        "venues/mail.html",
        {
            "venue": venue,
            "form": form,
            "recipients": recipients,
        },
    )


@login_required
def venue_export(request, pk):
    """Выгрузка участников площадки в Excel: ФИО, паспортные данные, адрес площадки."""
    venue = _managed_venue_or_403(request.user, pk)
    season = Season.objects.active()
    stage = _offline_stage(season)

    bookings = (
        (
            VenueBooking.objects.filter(venue=venue, stage=stage)
            .exclude(status=VenueBooking.Status.CANCELLED)
            .select_related("registration__user", "registration__user__profile")
            .order_by(
                "registration__user__profile__last_name",
                "registration__user__profile__first_name",
                "registration__user__email",
            )
        )
        if stage
        else VenueBooking.objects.none()
    )

    content = generate_venue_participants_excel(venue, bookings)

    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="venue-{venue.pk}-participants.xlsx"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response

@login_required
def offline_grading_export(request):
    """Выгрузка общей ведомости очного тура в Excel."""
    if not request.user.is_manager:
        raise PermissionDenied("Доступно только организаторам.")

    season = Season.objects.active()
    stage = _offline_stage(season)
    if not stage:
        raise Http404("Очный тур не найден.")

    context = _get_grading_context(request, season, stage)
    rows = context["rows"]
    problems = context["problems"]

    content = generate_offline_grading_excel(stage, rows, problems, request=request)

    today_str = date.today().strftime("%Y-%m-%d")
    filename = f"vedomost_ochny_tur_{today_str}.xlsx"

    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.core.files import protected_file_response
from apps.core.validators import validate_solution_file
from apps.participation.models import Registration, VenueBooking
from apps.seasons.models import Season, Stage

from .forms import GradeForm, ProblemForm, SubmissionForm
from .models import Grade, Problem, Score, Submission, SubmissionFile
from .scoring import total as scoring_total


def _online_stage(season):
    """Дистанционный тур, который показываем на вкладке."""
    return Stage.objects.current_or_next(season, Stage.Kind.ONLINE)


def _twin_stage(stage, kind):
    """Тот же тур в другом формате.

    Первый отборочный этап идёт и очно, и дистанционно; это один этап,
    пройти нужно что-то одно. Связь между форматами — общее поле «порядок».
    """
    if not stage:
        return None
    return (stage.season.stages.real()
            .filter(order=stage.order, kind=kind, is_published=True)
            .exclude(pk=stage.pk).first())


def _practice_problem(season):
    """Тренировочная задача из песочницы.

    Нужна, чтобы проверить загрузку решения в любой день, а не только
    когда идёт настоящий тур. Живёт в отдельном этапе с is_practice=True,
    поэтому в списке туров и на схеме не появляется.
    """
    if not season:
        return None
    return (Problem.objects.visible()
            .filter(stage__season=season, stage__is_practice=True)
            .order_by("number").first())


def _email_unconfirmed(user):
    """Участник вошёл, но почту не подтвердил (сессия со времён до проверки).

    Новые участники без подтверждения просто не могут войти (LoginForm).
    """
    return user.is_authenticated and user.is_participant and not user.email_confirmed


def problem_list(request):
    """Тур: расписание видно всем, сами задачи — только вошедшим участникам."""
    if _email_unconfirmed(request.user):
        messages.info(request, "Подтвердите почту, чтобы открыть задачи.")
        return redirect("accounts:resend_confirmation")
    season = Season.objects.active()
    stage = _online_stage(season)
    problems = (list(Problem.objects.visible().filter(stage=stage))
                if stage and request.user.is_authenticated else [])

    # К каждой задаче — последняя попытка участника, чтобы в списке
    # было видно не только «сдано», но и когда.
    if request.user.is_authenticated and stage:
        latest = {
            s.problem_id: s
            for s in Submission.objects.filter(user=request.user, problem__stage=stage, is_latest=True)
        }
        for problem in problems:
            problem.my_submission = latest.get(problem.pk)

    from apps.venues.models import Venue

    return render(request, "contest/problem_list.html", {
        "season": season, "stage": stage, "problems": problems,
        "practice": _practice_problem(season) if request.user.is_authenticated else None,
        "my_venues": Venue.objects.managed_by(request.user),
        "offline_twin": _twin_stage(stage, Stage.Kind.OFFLINE),
    })


def _problem_page(request, problem, form=None):
    """Страница задачи. Общая для просмотра и для повторного показа формы с ошибкой."""
    user = request.user
    attempts = Submission.objects.none()
    if user.is_authenticated and not user.is_manager:
        attempts = (Submission.objects
                    .filter(user=user, problem=problem)
                    .select_related("problem__stage", "grade")
                    .prefetch_related("files")
                    .order_by("-created_at"))
    attempts = list(attempts)

    can_review = user.is_authenticated and problem.can_be_reviewed_by(user)
    return render(request, "contest/problem_detail.html", {
        "problem": problem, "form": form or SubmissionForm(),
        # Последняя попытка — та, что пойдёт в проверку; остальные
        # показываем свёрнутыми, чтобы участник видел всю историю.
        "last_submission": attempts[0] if attempts else None,
        "earlier_submissions": attempts[1:],
        "can_edit": can_review,
        "can_review": can_review,
        "submission_count": (Submission.objects.filter(problem=problem, is_latest=True).count()
                             if can_review else 0),
    })


@login_required
def problem_detail(request, pk):
    if _email_unconfirmed(request.user):
        messages.info(request, "Подтвердите почту, чтобы открыть задачи.")
        return redirect("accounts:resend_confirmation")
    # Организатор может открыть любую задачу (включая неодобренные и задачи очного этапа до публикации),
    # чтобы посмотреть, как она будет выглядеть у участников.
    if request.user.is_authenticated and request.user.is_manager:
        problem = get_object_or_404(
            Problem.objects.select_related("stage__season", "created_by"),
            pk=pk,
        )
    else:
        problem = get_object_or_404(
            Problem.objects.visible().select_related("stage__season", "created_by"),
            pk=pk,
        )
    return _problem_page(request, problem)


@login_required
def submit(request, pk):
    problem = get_object_or_404(Problem.objects.visible(), pk=pk)
    if request.user.is_manager:
        raise PermissionDenied("Организаторы решения не сдают.")
    if not problem.accepts_submissions:
        messages.error(request, "Приём решений по этой задаче закрыт.")
        return redirect("contest:problem_detail", pk=pk)
    # Тренировочная задача открыта всем: она для проверки загрузки, а не
    # для участия. Настоящие — после анкеты и согласия на обработку ПД.
    if not problem.stage.is_practice and not request.user.can_participate:
        messages.error(request, "Чтобы сдавать решения, заполните анкету и загрузите "
                                "согласие на обработку персональных данных.")
        return redirect("accounts:profile")

    form = SubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        files = form.cleaned_data["files"]
        try:
            if len(files) > settings.MAX_FILES_PER_SUBMISSION:
                raise ValidationError(
                    f"Не больше {settings.MAX_FILES_PER_SUBMISSION} файлов за раз. "
                    "Соберите страницы в один PDF или .zip."
                )
            for f in files:
                validate_solution_file(f)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return _problem_page(request, problem, form)

        with transaction.atomic():
            # Блокируем строку участника до конца транзакции: двойное
            # нажатие «Отправить» даёт две попытки строго по очереди, и
            # «последней» остаётся ровно одна.
            User.objects.select_for_update().filter(pk=request.user.pk).first()
            # Предел попыток — защита диска: без него один человек может
            # загружать по 100 МБ, пока место на сервере не кончится.
            attempts = Submission.objects.filter(user=request.user, problem=problem).count()
            if attempts >= settings.MAX_ATTEMPTS_PER_PROBLEM:
                messages.error(
                    request,
                    f"По этой задаче уже {attempts} попыток — это предел. "
                    "Если нужно заменить решение, напишите организаторам.",
                )
                return redirect(reverse("contest:problem_detail", args=[pk]) + "#my-solution")
            submission = form.save(commit=False)
            submission.user = request.user
            submission.problem = problem
            submission.save()
            SubmissionFile.objects.bulk_create(
                [SubmissionFile(submission=submission, file=f, original_name=Path(f.name).name[:255])
                 for f in files]
            )
        messages.success(request, "Решение принято. Можно загрузить новую версию до дедлайна.")
        # Сразу к карточке с только что загруженным решением.
        return redirect(reverse("contest:problem_detail", args=[pk]) + "#my-solution")

    return _problem_page(request, problem, form)


@login_required
def submission_file(request, pk):
    """Файл решения — только автору и проверяющим этой задачи.

    Решения лежат вне открытого /media/: иначе любой, кто угадал путь,
    скачал бы чужую работу. Сам файл в проде отдаёт nginx
    (X-Accel-Redirect), Django лишь проверяет права — так большие
    сканы не держат воркер gunicorn.
    """
    sf = get_object_or_404(
        SubmissionFile.objects.select_related("submission__problem"), pk=pk
    )
    if not sf.submission.can_be_viewed_by(request.user):
        # 404, а не 403: не подтверждаем, что такой файл вообще есть.
        raise Http404
    return protected_file_response(request, sf.file, sf.filename)


@login_required
def my_submissions(request):
    """Что участник сдал и что получил.

    Баллы показываем только по этапам с опубликованными результатами:
    пока ведомость заполняется, оценки не должны утекать участникам.
    """
    subs = (Submission.objects
            .filter(user=request.user, is_latest=True)
            .select_related("problem", "problem__stage", "grade")
            .prefetch_related("files"))

    scores = []
    stage_results = []
    qualifying_notes = []
    season = Season.objects.active()
    if season:
        scores = list(Score.objects
                      .filter(registration__user=request.user,
                              problem__stage__results_published=True)
                      .select_related("problem", "problem__stage", "venue")
                      .order_by("problem__stage__order", "problem__stage_id", "problem__number"))

        stages_map = {}
        for s in scores:
            st = s.problem.stage
            if st.pk not in stages_map:
                stages_map[st.pk] = {
                    "stage": st,
                    "scores": [],
                    "venue": s.venue,
                }
            stages_map[st.pk]["scores"].append(s)
            if s.venue and not stages_map[st.pk]["venue"]:
                stages_map[st.pk]["venue"] = s.venue

        from apps.participation.models import VenueBooking
        user_bookings = {
            b.stage_id: b
            for b in VenueBooking.objects.filter(
                registration__user=request.user,
            ).select_related("venue")
        }

        for item in stages_map.values():
            item["total"] = scoring_total((s.problem, s.points) for s in item["scores"])
            item["has_mixed_venues"] = len({s.venue_id for s in item["scores"]}) > 1
            b = user_bookings.get(item["stage"].pk)
            if b:
                if not item["venue"]:
                    item["venue"] = b.venue
                if b.work_scan and item["stage"].results_published:
                    item["work_scan_url"] = b.get_scan_url()
            stage_results.append(item)

        # Выявляем этапы с одинаковым порядком (например, очный и онлайн отборы одного тура)
        by_order = {}
        for item in stage_results:
            by_order.setdefault(item["stage"].order, []).append(item)

        for order, items in by_order.items():
            if len(items) > 1:
                max_total = max(x["total"] for x in items)
                best_items = [x for x in items if x["total"] == max_total]
                for item in items:
                    item["is_twin"] = True
                    item["is_best_twin"] = (item in best_items)
                stages_titles = " и ".join(f"«{x['stage'].title}»" for x in items)
                best_val = max_total
                best_val_str = f"{best_val:.2f}".rstrip("0").rstrip(".") if "." in f"{best_val}" else f"{best_val}"
                qualifying_notes.append(
                    f"{stages_titles} — равнозначные форматы одного этапа. "
                    f"В зачёт отбора идёт лучший результат: {best_val_str} б. ({best_items[0]['stage'].title})."
                )

    return render(request, "contest/my_submissions.html", {
        "submissions": subs,
        "scores": scores,
        "stage_results": stage_results,
        "qualifying_notes": qualifying_notes,
        "total": scoring_total((s.problem, s.points) for s in scores) if scores else 0,
    })


# --- Проверка решений -------------------------------------------------------
#
# Организатор — это и проверяющий, и хозяин площадки: отдельной роли «жюри»
# нет. Поэтому проверка живёт на сайте, а не только в админке: чтобы
# посмотреть решения, человеку не нужен доступ в /admin/.


def _require_reviewer(user):
    if not user.can_review:
        raise PermissionDenied("Проверять решения могут только организаторы.")


def _format_points(val):
    if val is None:
        return ""
    return str(int(val)) if val == val.to_integral() else f"{val:.2f}".rstrip("0").rstrip(".")


@login_required
def review_list(request):
    """Сводная ведомость проверки дистанционного тура: матрица участников и задач."""
    _require_reviewer(request.user)

    season = Season.objects.active()
    stage = _online_stage(season)

    # Задачи текущего этапа (или все одобренные с решениями)
    if stage:
        problems = list(stage.problems.filter(status=Problem.Status.APPROVED))
    else:
        problems = list(Problem.objects.filter(status=Problem.Status.APPROVED))
    problems.sort(key=lambda p: p.sort_key)

    problem_id = request.GET.get("problem", "").strip()
    status_filter = request.GET.get("status", "todo")
    search_query = request.GET.get("q", "").strip()

    # Все последние решения по этим задачам
    submissions_qs = (
        Submission.objects.filter(is_latest=True, problem__in=problems)
        .select_related("problem", "user", "user__profile", "grade")
        .prefetch_related("files")
        .order_by("created_at")
    )

    if problem_id and problem_id.isdigit():
        submissions_qs = submissions_qs.filter(problem_id=int(problem_id))

    # Сгруппируем по пользователям
    user_submissions = {}
    users_order = []
    for sub in submissions_qs:
        if sub.user not in user_submissions:
            user_submissions[sub.user] = {}
            users_order.append(sub.user)
        user_submissions[sub.user][sub.problem_id] = sub

    # Обработка POST сохранения всей таблицы
    if request.method == "POST":
        saved = 0
        for sub in submissions_qs:
            raw = request.POST.get(f"score_{sub.pk}")
            if raw is not None:
                raw = raw.strip()
                if raw == "":
                    if hasattr(sub, "grade"):
                        sub.grade.score = None
                        sub.grade.status = Grade.Status.NEW
                        sub.grade.save()
                    Score.objects.filter(
                        registration__user=sub.user, problem=sub.problem
                    ).delete()
                else:
                    try:
                        points = Decimal(raw.replace(",", "."))
                    except InvalidOperation:
                        continue
                    grade, _ = Grade.objects.get_or_create(submission=sub)
                    grade.score = points
                    grade.reviewer = request.user
                    grade.status = Grade.Status.GRADED
                    grade.save()

                    reg, _ = Registration.objects.get_or_create(
                        user=sub.user, season=sub.problem.stage.season
                    )
                    Score.objects.update_or_create(
                        registration=reg,
                        problem=sub.problem,
                        defaults={
                            "points": points,
                            "entered_by": request.user,
                            "is_skipped": False,
                        },
                    )
                    saved += 1
        messages.success(request, f"Сохранено оценок: {saved}.")
        return redirect(request.get_full_path())

    # Формируем строки для отображения
    rows = []
    todo_count = 0
    for user in users_order:
        user_subs = user_submissions[user]
        profile = getattr(user, "profile", None)
        full_name = profile.full_name if profile and profile.full_name else user.email

        if search_query:
            q_lower = search_query.lower()
            if q_lower not in full_name.lower() and q_lower not in user.email.lower():
                continue

        has_todo = any(
            not hasattr(s, "grade") or s.grade.status != Grade.Status.GRADED
            for s in user_subs.values()
        )
        if has_todo:
            todo_count += 1

        if status_filter == "todo" and not has_todo:
            continue
        elif status_filter == "graded" and has_todo:
            continue

        cells = []
        row_total = Decimal("0")
        for p in problems:
            sub = user_subs.get(p.pk)
            grade = getattr(sub, "grade", None) if sub else None
            score = grade.score if grade and grade.score is not None else None
            if score is not None:
                row_total += score

            score_str = _format_points(score)

            cells.append({
                "problem": p,
                "submission": sub,
                "files": list(sub.files.all()) if sub else [],
                "grade": grade,
                "score_str": score_str,
                "status": grade.status if grade else None,
            })

        total_str = _format_points(row_total)

        rows.append({
            "user": user,
            "full_name": full_name,
            "cells": cells,
            "total": total_str,
        })

    if status_filter == "todo":
        filtered_subs = submissions_qs.filter(models.Q(grade__isnull=True) | ~models.Q(grade__status=Grade.Status.GRADED))
    elif status_filter == "graded":
        filtered_subs = submissions_qs.filter(grade__status=Grade.Status.GRADED)
    else:
        filtered_subs = submissions_qs

    return render(request, "contest/review_list.html", {
        "season": season,
        "stage": stage,
        "problems": problems,
        "selected_problem": problem_id,
        "status": status_filter,
        "search_query": search_query,
        "rows": rows,
        "todo_count": todo_count,
        "submissions": filtered_subs,
    })


@require_POST
@login_required
def review_save_grade(request):
    """AJAX-сохранение балла за дистанционную задачу."""
    _require_reviewer(request.user)

    if request.content_type == "application/json":
        data = json.loads(request.body)
    else:
        data = request.POST

    submission_id = data.get("submission_id")
    if not submission_id:
        return JsonResponse({"error": "No submission_id"}, status=400)

    sub = get_object_or_404(
        Submission.objects.select_related("problem__stage__season", "user"),
        pk=submission_id,
    )

    raw_score = str(data.get("score") if data.get("score") is not None else "").strip()
    grade = getattr(sub, "grade", None)

    if raw_score == "":
        if grade:
            grade.score = None
            grade.status = Grade.Status.NEW
            grade.save()
        Score.objects.filter(registration__user=sub.user, problem=sub.problem).delete()
    else:
        try:
            points = Decimal(raw_score.replace(",", "."))
        except InvalidOperation:
            return JsonResponse({"error": "Invalid number"}, status=400)

        if points < 0:
            return JsonResponse({"error": "Negative score"}, status=400)

        if not grade:
            grade = Grade(submission=sub)
        grade.score = points
        grade.reviewer = request.user
        grade.status = Grade.Status.GRADED
        grade.save()

        reg, _ = Registration.objects.get_or_create(
            user=sub.user, season=sub.problem.stage.season
        )
        Score.objects.update_or_create(
            registration=reg,
            problem=sub.problem,
            defaults={
                "points": points,
                "entered_by": request.user,
                "is_skipped": False,
            },
        )

    # Recalculate total for user in this stage
    stage_scores = Score.objects.filter(
        registration__user=sub.user, problem__stage=sub.problem.stage
    )
    total = sum((s.points for s in stage_scores if s.points is not None), Decimal("0"))
    total_str = _format_points(total)

    return JsonResponse({
        "status": "ok",
        "total": total_str,
        "grade_status": grade.status if grade else "new",
    })


@login_required
def review_detail(request, pk):
    """Одно решение: файлы рядом с формой оценки, без похода в админку."""
    _require_reviewer(request.user)

    submission = get_object_or_404(
        Submission.objects.select_related("problem", "user", "user__profile"), pk=pk
    )
    if not submission.problem.can_be_reviewed_by(request.user):
        raise PermissionDenied("Вы не назначены проверяющим по этой задаче.")
    grade = getattr(submission, "grade", None)
    form = GradeForm(request.POST or None, instance=grade,
                     max_score=submission.problem.max_score)

    if request.method == "POST" and form.is_valid():
        grade = form.save(commit=False)
        grade.submission = submission
        grade.reviewer = request.user
        grade.save()
        messages.success(request, "Оценка сохранена.")
        # Возвращаем в очередь с теми же фильтрами, чтобы проверять подряд.
        return redirect(_safe_back(request, request.POST.get("back")))

    return render(request, "contest/review_detail.html", {
        "submission": submission, "form": form, "grade": grade,
        "back": _safe_back(request, request.GET.get("back")),
        "history": (Submission.objects
                    .filter(user=submission.user, problem=submission.problem)
                    .exclude(pk=submission.pk)
                    .order_by("-created_at")),
    })


def _safe_back(request, url):
    """Адрес «вернуться в очередь» — только внутри сайта.

    Он приходит в ссылке (?back=…), и подставить туда можно что угодно:
    чужой сайт или javascript:. Всё, что не является адресом очереди
    на нашем сайте, заменяем на саму очередь.
    """
    fallback = reverse("contest:review_list")
    if url and url.startswith(fallback) and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return fallback


# --- Задачи: заводит организатор, одобряет администратор --------------------


@login_required
def problem_manage(request):
    """Список задач, которые человек вправе редактировать."""
    _require_reviewer(request.user)
    problems = (Problem.objects.editable_by(request.user)
                .select_related("stage", "created_by")
                .order_by("stage__order", "number"))
    return render(request, "contest/problem_manage.html", {
        "problems": problems,
        "pending_count": problems.filter(status=Problem.Status.PENDING).count(),
    })


@login_required
def problem_new(request):
    """Завести задачу. Она появится у участников только после одобрения."""
    _require_reviewer(request.user)
    form = ProblemForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        problem = form.save(commit=False)
        problem.created_by = request.user
        # Черновик или сразу на одобрение — решает кнопка, которой отправили форму.
        # Администратор может одобрить свою задачу сразу.
        if request.user.is_admin and "approve" in request.POST:
            problem.status = Problem.Status.APPROVED
        elif "submit_for_review" in request.POST:
            problem.status = Problem.Status.PENDING
        else:
            problem.status = Problem.Status.DRAFT
        problem.save()
        messages.success(request, _status_message(problem))
        return redirect("contest:problem_edit", pk=problem.pk)
    return render(request, "contest/problem_form.html",
                  {"form": form, "problem": None, "is_admin": request.user.is_admin})


@login_required
def problem_edit(request, pk):
    """Правка задачи автором, назначенным проверяющим или администратором.

    Администратор здесь же одобряет задачу или возвращает её автору
    с комментарием — без похода в Django-админку.
    """
    _require_reviewer(request.user)
    problem = get_object_or_404(Problem.objects.editable_by(request.user), pk=pk)
    form = ProblemForm(request.POST or None, request.FILES or None, instance=problem)
    is_admin = request.user.is_admin

    if request.method == "POST" and form.is_valid():
        problem = form.save(commit=False)
        comment = request.POST.get("moderation_comment", "").strip()
        if is_admin and "approve" in request.POST:
            problem.status = Problem.Status.APPROVED
            problem.moderation_comment = ""
        elif is_admin and "reject" in request.POST:
            if not comment:
                messages.error(request, "Напишите автору, что исправить: без комментария отклонить нельзя.")
                return render(request, "contest/problem_form.html",
                              {"form": form, "problem": problem, "is_admin": is_admin})
            problem.status = Problem.Status.REJECTED
            problem.moderation_comment = comment
        elif "submit_for_review" in request.POST:
            problem.status = Problem.Status.PENDING
        elif problem.status == Problem.Status.REJECTED:
            # Правка отклонённой задачи возвращает её в черновики:
            # иначе она так и останется помеченной как отклонённая.
            problem.status = Problem.Status.DRAFT
        problem.save()
        messages.success(request, _status_message(problem))
        return redirect("contest:problem_edit", pk=problem.pk)

    return render(request, "contest/problem_form.html",
                  {"form": form, "problem": problem, "is_admin": is_admin})


def _status_message(problem):
    if problem.status == Problem.Status.APPROVED:
        if problem.stage.starts_at > timezone.now():
            return (f"Задача одобрена. Участники увидят её, когда начнётся этап — "
                    f"{timezone.localtime(problem.stage.starts_at):%d.%m.%Y}.")
        return "Задача одобрена и видна участникам."
    if problem.status == Problem.Status.PENDING:
        return "Задача отправлена на одобрение администратору."
    if problem.status == Problem.Status.REJECTED:
        return "Задача возвращена автору с комментарием."
    return "Задача сохранена как черновик. Участники её пока не видят."

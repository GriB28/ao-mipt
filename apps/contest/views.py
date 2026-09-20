from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.validators import validate_solution_file
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


def problem_list(request):
    season = Season.objects.active()
    stage = _online_stage(season)
    problems = Problem.objects.visible().filter(stage=stage) if stage else Problem.objects.none()

    my_submissions = {}
    if request.user.is_authenticated and stage:
        my_submissions = {
            s.problem_id: s
            for s in Submission.objects.filter(user=request.user, problem__stage=stage, is_latest=True)
        }

    from apps.venues.models import Venue

    return render(request, "contest/problem_list.html", {
        "season": season, "stage": stage, "problems": problems,
        "my_submissions": my_submissions, "practice": _practice_problem(season),
        "my_venues": Venue.objects.managed_by(request.user),
        "offline_twin": _twin_stage(stage, Stage.Kind.OFFLINE),
    })


def problem_detail(request, pk):
    # Организатор должен открыть и неодобренную задачу — свою собственную,
    # чтобы посмотреть, как она будет выглядеть у участников.
    visible = Problem.objects.visible()
    if request.user.is_authenticated and request.user.is_manager:
        visible = Problem.objects.filter(
            models.Q(pk__in=visible) | models.Q(pk__in=Problem.objects.editable_by(request.user))
        )
    problem = get_object_or_404(visible, pk=pk)

    last = None
    if request.user.is_authenticated and not request.user.is_manager:
        last = Submission.objects.filter(user=request.user, problem=problem, is_latest=True).first()

    can_review = request.user.is_authenticated and problem.can_be_reviewed_by(request.user)
    return render(request, "contest/problem_detail.html", {
        "problem": problem, "form": SubmissionForm(), "last_submission": last,
        "can_edit": can_review,
        "can_review": can_review,
        "submission_count": (Submission.objects.filter(problem=problem, is_latest=True).count()
                             if can_review else 0),
    })


@login_required
def submit(request, pk):
    problem = get_object_or_404(Problem.objects.visible(), pk=pk)
    if not problem.accepts_submissions:
        messages.error(request, "Приём решений по этой задаче закрыт.")
        return redirect("contest:problem_detail", pk=pk)

    form = SubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        files = form.cleaned_data["files"]
        try:
            for f in files:
                validate_solution_file(f)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return render(request, "contest/problem_detail.html", {"problem": problem, "form": form})

        with transaction.atomic():
            submission = form.save(commit=False)
            submission.user = request.user
            submission.problem = problem
            submission.save()
            SubmissionFile.objects.bulk_create(
                [SubmissionFile(submission=submission, file=f) for f in files]
            )
        messages.success(request, "Решение принято. Можно загрузить новую версию до дедлайна.")
        return redirect("contest:problem_detail", pk=pk)

    return render(request, "contest/problem_detail.html", {"problem": problem, "form": form})


@login_required
def my_submissions(request):
    """Что участник сдал и что получил.

    Баллы показываем только по этапам с опубликованными результатами:
    пока ведомость заполняется, оценки не должны утекать участникам.
    """
    subs = (Submission.objects
            .filter(user=request.user, is_latest=True)
            .select_related("problem", "problem__stage", "grade"))

    scores = []
    season = Season.objects.active()
    if season:
        scores = (Score.objects
                  .filter(registration__user=request.user,
                          problem__stage__results_published=True)
                  .select_related("problem", "problem__stage", "venue")
                  .order_by("problem__stage__order", "problem__number"))

    return render(request, "contest/my_submissions.html", {
        "submissions": subs,
        "scores": scores,
        # Складываем через scoring.total: задачи не равнозначны, и когда
        # появятся веса, это место посчитает их само.
        "total": scoring_total((s.problem, s.points) for s in scores),
    })


# --- Проверка решений -------------------------------------------------------
#
# Организатор — это и проверяющий, и хозяин площадки: отдельной роли «жюри»
# нет. Поэтому проверка живёт на сайте, а не только в админке: чтобы
# посмотреть решения, человеку не нужен доступ в /admin/.


def _require_reviewer(user):
    if not user.can_review:
        raise PermissionDenied("Проверять решения могут только организаторы.")


@login_required
def review_list(request):
    """Очередь проверки: что прислали и что ещё не посмотрели."""
    _require_reviewer(request.user)

    # Организатор видит решения только тех задач, где он автор или
    # назначен проверяющим; администратор — все.
    mine = Problem.objects.editable_by(request.user)
    submissions = (Submission.objects
                   .filter(is_latest=True, problem__in=mine)
                   .select_related("problem", "problem__stage", "user", "user__profile", "grade")
                   .order_by("problem__stage__order", "problem__number", "created_at"))

    problem_id = request.GET.get("problem")
    if problem_id:
        submissions = submissions.filter(problem_id=problem_id)

    # По умолчанию показываем непроверенные: именно за ними сюда заходят.
    status = request.GET.get("status", "todo")
    if status == "todo":
        submissions = submissions.exclude(grade__status=Grade.Status.GRADED)
    elif status == "graded":
        submissions = submissions.filter(grade__status=Grade.Status.GRADED)

    problems = (mine.filter(submissions__isnull=False)
                .distinct()
                .select_related("stage")
                .order_by("stage__order", "number"))

    return render(request, "contest/review_list.html", {
        "submissions": submissions,
        "problems": problems,
        "selected_problem": problem_id,
        "status": status,
        "todo_count": Submission.objects.filter(is_latest=True, problem__in=mine)
                                        .exclude(grade__status=Grade.Status.GRADED).count(),
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
        return redirect(request.POST.get("back") or "contest:review_list")

    return render(request, "contest/review_detail.html", {
        "submission": submission, "form": form, "grade": grade,
        "back": request.GET.get("back", ""),
        "history": (Submission.objects
                    .filter(user=submission.user, problem=submission.problem)
                    .exclude(pk=submission.pk)
                    .order_by("-created_at")),
    })


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
        problem.status = (Problem.Status.PENDING if "submit_for_review" in request.POST
                          else Problem.Status.DRAFT)
        problem.save()
        messages.success(request, _status_message(problem))
        return redirect("contest:problem_edit", pk=problem.pk)
    return render(request, "contest/problem_form.html", {"form": form, "problem": None})


@login_required
def problem_edit(request, pk):
    """Правка задачи автором или назначенным проверяющим."""
    _require_reviewer(request.user)
    problem = get_object_or_404(Problem.objects.editable_by(request.user), pk=pk)
    form = ProblemForm(request.POST or None, request.FILES or None, instance=problem)

    if request.method == "POST" and form.is_valid():
        problem = form.save(commit=False)
        if "submit_for_review" in request.POST:
            problem.status = Problem.Status.PENDING
        elif problem.status == Problem.Status.REJECTED:
            # Правка отклонённой задачи возвращает её в черновики:
            # иначе она так и останется помеченной как отклонённая.
            problem.status = Problem.Status.DRAFT
        problem.save()
        messages.success(request, _status_message(problem))
        return redirect("contest:problem_edit", pk=problem.pk)

    return render(request, "contest/problem_form.html", {"form": form, "problem": problem})


def _status_message(problem):
    if problem.status == Problem.Status.PENDING:
        return "Задача отправлена на одобрение администратору."
    return "Задача сохранена как черновик. Участники её пока не видят."

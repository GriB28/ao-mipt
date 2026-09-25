from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render

from apps.contest.models import Problem
from apps.seasons.models import Season

from .forms import LectureForm
from .models import ArchiveMaterial, Lecture, News, Page, Playlist, Topic


def news_list(request):
    return render(request, "content/news_list.html", {"news": News.objects.published()})


def news_detail(request, slug):
    return render(request, "content/news_detail.html",
                  {"item": get_object_or_404(News.objects.published(), slug=slug)})


def lecture_list(request):
    """Лекции этого сезона.

    Плейлистов здесь нет намеренно: все наши плейлисты — записи прошлых
    лет, им место в архиве. Лекции текущего сезона выкладываются по одной
    во ВКонтакте, и на этой странице должны быть видны сразу они.
    """
    season = Season.objects.active()
    lectures = Lecture.objects.published().filter(season=season) if season else Lecture.objects.none()
    return render(request, "content/lecture_list.html", {
        "lectures": lectures, "playlists": [], "season": season, "is_archive": False,
    })


def lecture_archive(request):
    """
    Лекции и плейлисты прошлых сезонов.

    Полсотни записей списком — это стена, в которой ничего не найти,
    поэтому они разложены по разделам (физика, программирование) и темам
    внутри них. Фильтры — по разделу и по сезону: тем много, и выбирать
    из них в списке неудобно, они и так видны заголовками.
    """
    season = Season.objects.active()
    lectures = (Lecture.objects.published()
                .select_related("season", "topic")
                .order_by("topic__section", "topic__order", "-season__year", "title"))
    playlists = Playlist.objects.published().select_related("season")
    if season:
        lectures = lectures.exclude(season=season)
        playlists = playlists.exclude(season=season)

    # Список сезонов — по всем лекциям архива, а не по отфильтрованным:
    # иначе после выбора сезона в списке остался бы он один.
    season_choices = (Season.objects.filter(lectures__in=lectures)
                      .distinct().order_by("-year"))

    chosen = {
        "section": request.GET.get("section", ""),
        "season": request.GET.get("season", ""),
    }
    if chosen["section"]:
        lectures = lectures.filter(topic__section=chosen["section"])
    if chosen["season"]:
        lectures = lectures.filter(season__slug=chosen["season"])

    return render(request, "content/lecture_list.html", {
        "sections": _group_by_topic(lectures),
        "lectures": lectures,
        "playlists": playlists if not any(chosen.values()) else [],
        "season": None,
        "is_archive": True,
        "season_choices": season_choices,
        "chosen": chosen,
        "section_choices": Topic.Section.choices,
    })


def _group_by_topic(lectures):
    """Раскладывает лекции: раздел → тема → лекции.

    Группируем в Python, а не запросами: полсотни записей уже загружены,
    и лишние обращения к базе тут ничего не ускорят.
    """
    sections = {}
    for lecture in lectures:
        topic = lecture.topic
        section = topic.section if topic else ""
        section_title = topic.get_section_display() if topic else "Прочее"
        sections.setdefault((section, section_title), {}) \
                .setdefault(topic.title if topic else "Без темы", []).append(lecture)

    # Порядок разделов — как объявлено в модели: физика, программирование,
    # общее. По коду раздела сортировка дала бы алфавит, и «Общее»
    # оказалось бы первым.
    priority = {value: number for number, (value, _) in enumerate(Topic.Section.choices)}
    ordered = sorted(sections.items(), key=lambda item: priority.get(item[0][0], 99))
    return [
        (title, list(topics.items()), sum(len(v) for v in topics.values()))
        for (_, title), topics in ordered
    ]


def lecture_detail(request, season_slug, slug):
    """Страница лекции с проигрывателем."""
    lecture = get_object_or_404(
        Lecture.objects.published().select_related("season"),
        season__slug=season_slug, slug=slug,
    )
    return render(request, "content/lecture_detail.html", {"lecture": lecture})


def problem_archive(request):
    """
    Архив прошлых лет.

    Показываем два слоя сразу:
      * разобранные по задачам (модель Problem) — если до них дошли руки;
      * материалы тура целиком (ArchiveMaterial) — всё остальное.

    Так архив полезен с первого дня, а разбор по задачам можно
    доделывать постепенно, не блокируя публикацию.
    """
    # В архиве только прошедшие сезоны: текущий живёт на главной и в
    # разделах туров, и его задачи не должны попадать сюда раньше времени.
    # Плюс отсекаем сезоны, где смотреть нечего.
    seasons = list(
        Season.objects.published()
        .exclude(is_active=True)
        .filter(models.Q(archive_materials__isnull=False) | models.Q(stages__problems__isnull=False))
        .distinct()
        .order_by("-year")
    )
    year = request.GET.get("year")

    selected = None
    if year:
        selected = next((s for s in seasons if str(s.year) == year), None)
    elif seasons:
        selected = seasons[0]

    problems, materials_by_stage = [], []
    if selected:
        problems = (Problem.objects
                    .filter(status=Problem.Status.APPROVED, stage__season=selected)
                    .select_related("stage")
                    .order_by("stage__order", "number"))

        materials = (ArchiveMaterial.objects.published()
                     .filter(season=selected)
                     .select_related("stage")
                     .order_by("stage__order", "stage__starts_at",
                               "problem_number", "title"))

        # Группируем: этап → тип материала. Порядок типов задаётся
        # KIND_ORDER, а не алфавитом: условия и разборы сверху,
        # данные к задачам и код — ниже.
        grouped = {}
        for material in materials:
            stage_title = material.stage.title if material.stage else "Без этапа"
            grouped.setdefault(stage_title, {}).setdefault(material.kind, []).append(material)

        order = ArchiveMaterial.KIND_ORDER
        materials_by_stage = [
            (
                stage_title,
                [
                    (items[0].get_kind_display(), items)
                    for _, items in sorted(kinds.items(), key=lambda kv: order.get(kv[0], 99))
                ],
            )
            for stage_title, kinds in grouped.items()
        ]

    return render(request, "content/problem_archive.html", {
        "seasons": seasons,
        "selected": selected,
        "problems": problems,
        "materials_by_stage": materials_by_stage,
    })


def page(request, slug):
    return render(request, "content/page.html",
                  {"page": get_object_or_404(Page.objects.published(), slug=slug)})


# --- Лекции: добавляет организатор, одобряет администратор ------------------


def _require_manager(user):
    if not (user.is_authenticated and user.is_manager):
        raise PermissionDenied("Добавлять лекции могут только организаторы.")


@login_required
def lecture_manage(request):
    """Список лекций, которые человек вправе править."""
    _require_manager(request.user)
    lectures = (Lecture.objects.editable_by(request.user)
                .select_related("season", "created_by")
                .order_by("-held_at"))
    return render(request, "content/lecture_manage.html", {
        "lectures": lectures,
        "pending_count": lectures.filter(status=Lecture.Status.PENDING).count(),
    })


@login_required
def lecture_new(request):
    """Добавить лекцию. Участники увидят её после одобрения."""
    _require_manager(request.user)
    form = LectureForm(request.POST or None, request.FILES or None,
                       initial={"season": Season.objects.active()})
    if request.method == "POST" and form.is_valid():
        lecture = form.save(commit=False)
        lecture.created_by = request.user
        lecture.status = (Lecture.Status.PENDING if "submit_for_review" in request.POST
                          else Lecture.Status.DRAFT)
        lecture.save()
        messages.success(request, _lecture_message(lecture))
        return redirect("content:lecture_edit", pk=lecture.pk)
    return render(request, "content/lecture_form.html", {"form": form, "lecture": None})


@login_required
def lecture_edit(request, pk):
    """Правка своей лекции."""
    _require_manager(request.user)
    lecture = get_object_or_404(Lecture.objects.editable_by(request.user), pk=pk)
    form = LectureForm(request.POST or None, request.FILES or None, instance=lecture)

    if request.method == "POST" and form.is_valid():
        lecture = form.save(commit=False)
        if "submit_for_review" in request.POST:
            lecture.status = Lecture.Status.PENDING
        elif lecture.status == Lecture.Status.REJECTED:
            # Правка отклонённой лекции возвращает её в черновики.
            lecture.status = Lecture.Status.DRAFT
        lecture.save()
        messages.success(request, _lecture_message(lecture))
        return redirect("content:lecture_edit", pk=lecture.pk)

    return render(request, "content/lecture_form.html", {"form": form, "lecture": lecture})


def _lecture_message(lecture):
    if lecture.status == Lecture.Status.PENDING:
        return "Лекция отправлена на одобрение администратору."
    return "Лекция сохранена как черновик. Участники её пока не видят."

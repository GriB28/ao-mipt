from django.contrib import admin

from .models import Grade, Problem, ProblemAttachment, Score, Submission, SubmissionFile


class AttachmentInline(admin.TabularInline):
    model = ProblemAttachment
    extra = 1


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    """
    Одобрение задач.

    Задачу заводит организатор и отправляет на одобрение; участники видят
    её только после статуса «Одобрена». Здесь же администратор назначает
    дополнительных проверяющих — кроме автора задачи.
    """

    list_display = ("number", "title", "stage", "status", "created_by", "reviewer_count")
    list_filter = ("stage__season", "stage", "status")
    search_fields = ("title",)
    filter_horizontal = ("reviewers",)
    autocomplete_fields = ("created_by",)
    inlines = [AttachmentInline]
    actions = ["approve", "reject"]

    @admin.display(description="проверяющих")
    def reviewer_count(self, obj):
        # Автор задачи проверяет всегда, поэтому считаем «плюс автор».
        return obj.reviewers.count() + (1 if obj.created_by_id else 0)

    @admin.action(description="Одобрить выбранные задачи")
    def approve(self, request, queryset):
        updated = queryset.update(status=Problem.Status.APPROVED)
        self.message_user(request, f"Одобрено задач: {updated}. Участники их увидят.")

    @admin.action(description="Отклонить выбранные задачи")
    def reject(self, request, queryset):
        updated = queryset.update(status=Problem.Status.REJECTED)
        self.message_user(request, f"Отклонено задач: {updated}. Впишите комментарий автору.")


class SubmissionFileInline(admin.TabularInline):
    model = SubmissionFile
    extra = 0
    readonly_fields = ("file",)


class GradeInline(admin.StackedInline):
    model = Grade
    extra = 0


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    """Рабочее место проверяющего: фильтр «не проверено» + переход по задачам."""

    list_display = ("problem", "user", "created_at", "is_late", "is_latest", "grade_status", "grade_score")
    list_filter = ("problem__stage", "problem", "is_latest", "is_late", "grade__status")
    search_fields = ("user__email", "user__profile__last_name")
    readonly_fields = ("user", "problem", "created_at", "is_late")
    inlines = [SubmissionFileInline, GradeInline]
    date_hierarchy = "created_at"

    @admin.display(description="статус проверки")
    def grade_status(self, obj):
        return getattr(obj, "grade", None) and obj.grade.get_status_display() or "не проверено"

    @admin.display(description="балл")
    def grade_score(self, obj):
        return getattr(obj, "grade", None) and obj.grade.score


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("submission", "score", "status", "reviewer")
    list_filter = ("status", "reviewer", "submission__problem")


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    """Баллы, внесённые с очных площадок и по итогам проверки."""

    list_display = ("registration", "problem", "points", "venue", "entered_by")
    list_filter = ("problem__stage", "venue", "problem")
    search_fields = ("registration__user__email", "registration__user__profile__last_name")
    list_select_related = ("registration__user", "problem", "venue")

from django.contrib import admin
from django.utils.html import format_html

from .models import ArchiveMaterial, Lecture, News, Page, Photo, Playlist


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "season", "published_at", "is_published")
    list_filter = ("season", "is_published")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "body")


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ("title", "season", "platform_title", "order", "is_published")
    list_filter = ("season", "is_published")
    list_editable = ("order", "season")
    search_fields = ("title",)


@admin.register(Lecture)
class LectureAdmin(admin.ModelAdmin):
    """
    Одобрение лекций.

    Лекцию добавляет организатор, участники видят её после одобрения.
    Ошибиться ссылкой на видео легко, а лекции — лицо раздела.
    """

    list_display = ("title", "season", "lecturer", "platform_title", "held_at",
                    "status", "created_by")
    list_filter = ("season", "status")
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "lecturer")
    autocomplete_fields = ("created_by",)
    actions = ["approve", "reject"]

    @admin.action(description="Одобрить выбранные лекции")
    def approve(self, request, queryset):
        updated = queryset.update(status=Lecture.Status.APPROVED)
        self.message_user(request, f"Одобрено лекций: {updated}. Участники их увидят.")

    @admin.action(description="Отклонить выбранные лекции")
    def reject(self, request, queryset):
        updated = queryset.update(status=Lecture.Status.REJECTED)
        self.message_user(request, f"Отклонено лекций: {updated}. Впишите комментарий автору.")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "show_in_menu", "menu_order", "is_published")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ArchiveMaterial)
class ArchiveMaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "season", "kind", "problem_number", "size_display", "is_published")
    list_filter = ("season", "kind", "stage", "is_published")
    search_fields = ("title", "description", "source_path")
    list_editable = ("problem_number",)
    readonly_fields = ("source_path", "size_bytes")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    """
    Фотографии финалов. Загружаются пачкой после каждого тура.

    Год ставится полем «сезон» — по нему снимки группируются в галерее
    на странице финала.
    """

    list_display = ("preview", "caption", "season", "order", "is_published")
    list_filter = ("season", "is_published")
    list_editable = ("caption", "season", "order", "is_published")
    search_fields = ("caption",)

    @admin.display(description="снимок")
    def preview(self, obj):
        if not obj.image:
            return "—"
        return format_html('<img src="{}" style="height:48px;border-radius:4px">', obj.image.url)

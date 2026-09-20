from django.contrib import admin

from .models import Season, Stage


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0
    fields = ("order", "kind", "title", "slug", "starts_at", "ends_at", "is_published")
    ordering = ("order",)


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("title", "year", "is_active", "is_published")
    list_filter = ("is_active", "is_published")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [StageInline]


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    """
    Этапы сезона. Даты правятся здесь, а не в коде.

    Начало ставьте на 00:00:00, дедлайн — на 23:59:59: «по 15 января»
    должно означать весь день 15 января, а не ноль часов, когда приём
    на самом деле уже закрыт.
    """

    list_display = ("title", "season", "order", "kind", "starts_at", "ends_at",
                    "is_practice", "is_published")
    list_filter = ("season", "kind", "is_published", "is_practice")
    list_editable = ("order",)
    date_hierarchy = "starts_at"



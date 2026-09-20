from django.contrib import admin
from django.db.models import Case, IntegerField, Value, When
from django.utils.html import format_html

from .models import Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    """
    Модерация площадок.

    Организатор создаёт площадку на сайте (/offline/apply/), она попадает
    сюда со статусом «На модерации» и до одобрения не видна ни на карте,
    ни в записи. Чтобы не искать такие заявки глазами, список по умолчанию
    отсортирован так, что они идут первыми, а в колонке «статус» они
    подсвечены.
    """

    list_display = ("title", "city", "region", "booked_count", "status_badge", "is_visible")
    list_filter = ("status", "is_visible", "region", "seasons")
    search_fields = ("title", "city", "address", "contact_name")
    filter_horizontal = ("managers", "seasons")
    actions = ["approve", "reject"]
    readonly_fields = ("created_by", "created_at", "updated_at")

    def get_queryset(self, request):
        """Заявки на модерации — наверх списка.

        Сортировать по самому полю status нельзя: по алфавиту «pending»
        встаёт между «draft» и «rejected». Поэтому считаем отдельный
        ключ сортировки, где ожидающие одобрения идут первыми.
        """
        return super().get_queryset(request).annotate(
            _moderation_first=Case(
                When(status=Venue.Status.PENDING, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("_moderation_first", "region", "city", "title")

    @admin.display(description="статус", ordering="status")
    def status_badge(self, obj):
        if obj.status == Venue.Status.PENDING:
            return format_html('<b style="color:#b45309">● {}</b>', obj.get_status_display())
        return obj.get_status_display()

    @admin.action(description="Одобрить выбранные площадки")
    def approve(self, request, queryset):
        updated = queryset.update(status=Venue.Status.APPROVED)
        self.message_user(request, f"Одобрено площадок: {updated}. Они появились на карте.")

    @admin.action(description="Отклонить выбранные площадки")
    def reject(self, request, queryset):
        updated = queryset.update(status=Venue.Status.REJECTED)
        self.message_user(request, f"Отклонено площадок: {updated}")

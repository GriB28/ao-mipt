from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Value, When
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
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

    list_display = (
        "title",
        "city",
        "region",
        "default_variant",
        "event_date",
        "booked_count",
        "status_badge",
        "is_visible",
        "stage_passed",
        "registration_closed",
        "toggle_registration_button",
        "book_link",
    )
    list_editable = ("stage_passed", "registration_closed")
    list_filter = ("status", "default_variant", "is_visible", "stage_passed", "registration_closed", "region", "seasons")
    search_fields = ("title", "city", "address", "contact_name")
    filter_horizontal = ("managers", "seasons")
    actions = [
        "approve",
        "reject",
        "mark_stage_passed",
        "mark_stage_not_passed",
        "lock_registration",
        "unlock_registration",
    ]
    readonly_fields = ("created_by", "created_at", "updated_at")

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "managers":
            from apps.accounts.models import User
            kwargs["queryset"] = User.objects.exclude(role=User.Role.PARTICIPANT)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

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

    @admin.display(description="записалось")
    def booked_count(self, obj):
        return obj.booked_count()

    @admin.display(description="статус", ordering="status")
    def status_badge(self, obj):
        if obj.status == Venue.Status.PENDING:
            return format_html('<b style="color:#b45309">● {}</b>', obj.get_status_display())
        return obj.get_status_display()

    @admin.display(description="ручная запись")
    def book_link(self, obj):
        url = reverse("admin:participation_venuebooking_add") + f"?venue={obj.pk}"
        return format_html('<a class="button" style="padding: 2px 8px; font-size: 11px;" href="{}">+ Записать</a>', url)

    @admin.action(description="Одобрить выбранные площадки")
    def approve(self, request, queryset):
        updated = queryset.update(status=Venue.Status.APPROVED)
        self.message_user(request, f"Одобрено площадок: {updated}. Они появились на карте.")

    @admin.action(description="Отклонить выбранные площадки")
    def reject(self, request, queryset):
        updated = queryset.update(status=Venue.Status.REJECTED)
        self.message_user(request, f"Отклонено площадок: {updated}")

    @admin.action(description="Отметить выбранные площадки: этап прошёл")
    def mark_stage_passed(self, request, queryset):
        updated = queryset.update(stage_passed=True)
        self.message_user(request, f"Отмечено площадок: {updated}. На карте они стали серыми.")

    @admin.action(description="Снять отметку «этап прошёл» с выбранных площадок")
    def mark_stage_not_passed(self, request, queryset):
        updated = queryset.update(stage_passed=False)
        self.message_user(request, f"Снята отметка с площадок: {updated}.")

    @admin.action(description="Заблокировать запись на выбранных площадках")
    def lock_registration(self, request, queryset):
        updated = queryset.update(registration_closed=True)
        self.message_user(request, f"Заблокирована запись на площадках: {updated}.")

    @admin.action(description="Разблокировать запись на выбранных площадках")
    def unlock_registration(self, request, queryset):
        updated = queryset.update(registration_closed=False)
        self.message_user(request, f"Разблокирована запись на площадках: {updated}.")

    @admin.display(description="блокировка")
    def toggle_registration_button(self, obj):
        url = reverse("admin:venues_venue_toggle_registration", args=[obj.pk])
        if obj.registration_closed:
            return format_html(
                '<a class="button" style="padding: 2px 8px; font-size: 11px; background: #059669; color: white; border: none; white-space: nowrap;" href="{}">Разблокировать</a>',
                url,
            )
        return format_html(
            '<a class="button" style="padding: 2px 8px; font-size: 11px; background: #dc2626; color: white; border: none; white-space: nowrap;" href="{}">Заблокировать</a>',
            url,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:venue_id>/toggle-registration/",
                self.admin_site.admin_view(self.toggle_registration_view),
                name="venues_venue_toggle_registration",
            ),
        ]
        return custom_urls + urls

    def toggle_registration_view(self, request, venue_id):
        venue = get_object_or_404(Venue, pk=venue_id)
        if not self.has_change_permission(request, venue):
            raise PermissionDenied
        venue.registration_closed = not venue.registration_closed
        venue.save(update_fields=["registration_closed"])
        status_msg = "заблокирована" if venue.registration_closed else "разблокирована"
        self.message_user(request, f"Запись на площадку «{venue.title}» {status_msg}.")
        referer = request.META.get("HTTP_REFERER")
        return HttpResponseRedirect(referer or reverse("admin:venues_venue_changelist"))


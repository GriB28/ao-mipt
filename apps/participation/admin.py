from django.contrib import admin

from .models import Registration, VenueBooking


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("user", "season", "grade")
    list_filter = ("season", "grade")
    search_fields = ("user__email", "user__profile__last_name")
    autocomplete_fields = ("user",)


@admin.register(VenueBooking)
class VenueBookingAdmin(admin.ModelAdmin):
    """
    Кто на какую площадку записался.

    Записываются участники сами, на странице площадки. Здесь запись можно
    посмотреть, перенести на другую площадку или отметить статусом
    «Пришёл» после тура — для списков и ведомостей.
    """

    list_display = ("registration", "stage", "venue", "variant", "held_at", "has_scan", "status")
    list_filter = ("stage", "variant", "status", "venue__region", "venue")
    search_fields = ("registration__user__email", "registration__user__profile__last_name", "venue__title")
    autocomplete_fields = ("venue",)
    list_select_related = ("registration__user", "stage", "venue")

    @admin.display(description="скан", boolean=True)
    def has_scan(self, obj):
        return bool(obj.work_scan)

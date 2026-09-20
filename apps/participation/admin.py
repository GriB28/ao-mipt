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

    list_display = ("registration", "stage", "venue", "status")
    list_filter = ("stage", "status", "venue__region", "venue")
    search_fields = ("registration__user__email", "venue__title")
    autocomplete_fields = ("venue",)
    list_select_related = ("registration__user", "stage", "venue")

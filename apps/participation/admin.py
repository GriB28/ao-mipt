import json

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html

from apps.accounts.models import User
from apps.seasons.models import Season, Stage

from .forms import VenueBookingAdminForm
from .models import Registration, VenueBooking


def _text_variants(text: str) -> set[str]:
    """Генерация вариантов регистра для регистронезависимого поиска в SQLite и PostgreSQL."""
    variants = {text, text.lower(), text.upper(), text.capitalize()}
    variants.add(text.title())
    return {v for v in variants if v}


def _make_field_q(field_name: str, word: str) -> models.Q:
    q = models.Q()
    for variant in _text_variants(word):
        q |= models.Q(**{f"{field_name}__icontains": variant})
    return q


def get_seasons_venues_data() -> dict:
    """Сбор данных по сезонам, очным этапам и площадкам для динамического переключения в форме."""
    seasons = Season.objects.prefetch_related("stages", "venues").all().order_by("-year")
    data = {}
    for season in seasons:
        offline_stages = [
            st for st in season.stages.all()
            if not st.is_practice and st.has_offline
        ]
        offline_stages.sort(key=lambda x: (x.order, x.starts_at))
        default_stage = (
            Stage.objects.current_or_next(season, Stage.Kind.OFFLINE)
            or (offline_stages[0] if offline_stages else None)
        )

        stages_list = [
            {
                "id": st.id,
                "title": st.title,
                "order": st.order,
                "kind": st.kind,
                "is_default": bool(default_stage and st.id == default_stage.id),
            }
            for st in offline_stages
        ]

        venues = list(season.venues.all().order_by("region", "city", "title"))
        venues_list = []
        for v in venues:
            booked_count = VenueBooking.objects.filter(
                venue=v,
                stage__season=season,
            ).exclude(status=VenueBooking.Status.CANCELLED).count()

            venues_list.append({
                "id": v.id,
                "title": v.title,
                "short_title": v.short_title or v.title,
                "region": v.region,
                "city": v.city,
                "address": v.address,
                "status": v.status,
                "is_public": v.is_public,
                "booked_count": booked_count,
            })

        data[str(season.id)] = {
            "id": season.id,
            "title": season.title,
            "years_label": season.years_label,
            "is_active": season.is_active,
            "stages": stages_list,
            "venues": venues_list,
        }
    return data


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("user", "participant_name", "season", "grade", "venue_booking_link")
    list_filter = ("season", "grade")
    search_fields = (
        "user__email",
        "user__profile__last_name",
        "user__profile__first_name",
    )
    autocomplete_fields = ("user",)
    list_select_related = ("user", "user__profile", "season")

    @admin.display(description="ФИО", ordering="user__profile__last_name")
    def participant_name(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.full_name if (profile and profile.full_name) else "—"

    @admin.display(description="запись на точку")
    def venue_booking_link(self, obj):
        booking = obj.bookings.exclude(status=VenueBooking.Status.CANCELLED).select_related("venue").first()
        if booking:
            change_url = reverse("admin:participation_venuebooking_change", args=[booking.pk])
            return format_html('<a href="{}">{}</a>', change_url, booking.venue.title)
        add_url = reverse("admin:participation_venuebooking_add") + f"?user={obj.user_id}&season={obj.season_id}"
        return format_html('<a class="button" style="padding: 2px 8px; font-size: 11px;" href="{}">+ Записать</a>', add_url)


@admin.register(VenueBooking)
class VenueBookingAdmin(admin.ModelAdmin):
    """
    Управление записями участников на точки проведения очного этапа.

    Позволяет администратору удобно записать участника на площадку вручную
    с поиском по email или ФИО, выбором сезона и выпадающим списком точек
    проведения этого сезона.
    """

    form = VenueBookingAdminForm
    change_form_template = "admin/participation/venuebooking/change_form.html"

    class Media:
        js = (
            "admin/js/vendor/jquery/jquery.js",
            "admin/js/vendor/select2/select2.full.js",
            "admin/js/vendor/select2/i18n/ru.js",
            "admin/js/jquery.init.js",
        )
        css = {
            "screen": (
                "admin/css/vendor/select2/select2.css",
                "admin/css/autocomplete.css",
            )
        }

    list_display = ("participant_name", "user_email", "season_title", "stage", "venue", "status")
    list_filter = ("stage__season", "stage", "status", "venue__region", "venue")
    search_fields = (
        "registration__user__email",
        "registration__user__profile__last_name",
        "registration__user__profile__first_name",
        "registration__user__profile__middle_name",
        "venue__title",
        "venue__city",
    )
    list_select_related = (
        "registration__user",
        "registration__user__profile",
        "registration__season",
        "stage",
        "stage__season",
        "venue",
    )

    @admin.display(description="участник (ФИО)", ordering="registration__user__profile__last_name")
    def participant_name(self, obj):
        profile = getattr(obj.registration.user, "profile", None)
        name = profile.full_name if profile else ""
        return name or "—"

    @admin.display(description="e-mail", ordering="registration__user__email")
    def user_email(self, obj):
        return obj.registration.user.email

    @admin.display(description="сезон", ordering="stage__season__year")
    def season_title(self, obj):
        return obj.stage.season.title

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "search-participants/",
                self.admin_site.admin_view(self.search_participants_view),
                name="participation_venuebooking_search_participants",
            ),
            path(
                "season-venues/",
                self.admin_site.admin_view(self.season_venues_view),
                name="participation_venuebooking_season_venues",
            ),
        ]
        return custom_urls + urls

    def search_participants_view(self, request):
        """AJAX-поиск участников по email или ФИО с переключателем режима фильтрации."""
        if not self.has_view_permission(request):
            raise PermissionDenied

        query = request.GET.get("q", "").strip()
        by = request.GET.get("by", "all")  # all, email, name

        users = User.objects.select_related("profile").all()
        if query:
            words = [w for w in query.split() if w]
            for word in words:
                if by == "email":
                    users = users.filter(_make_field_q("email", word))
                elif by == "name":
                    users = users.filter(
                        _make_field_q("profile__last_name", word)
                        | _make_field_q("profile__first_name", word)
                        | _make_field_q("profile__middle_name", word)
                    )
                else:  # all
                    users = users.filter(
                        _make_field_q("email", word)
                        | _make_field_q("profile__last_name", word)
                        | _make_field_q("profile__first_name", word)
                        | _make_field_q("profile__middle_name", word)
                    )

        users = users.order_by(
            models.Case(
                models.When(role=User.Role.PARTICIPANT, then=models.Value(0)),
                default=models.Value(1),
                output_field=models.IntegerField(),
            ),
            "email",
        )[:30]

        results = []
        for u in users:
            prof = getattr(u, "profile", None)
            full_name = prof.full_name if prof else ""
            grade_str = f"{prof.grade} класс" if (prof and prof.grade) else ""
            loc_parts = filter(None, [getattr(prof, "city", None), getattr(prof, "school", None)])
            loc_str = ", ".join(loc_parts)

            results.append({
                "id": u.pk,
                "email": u.email,
                "full_name": full_name or "",
                "has_name": bool(full_name),
                "grade": grade_str,
                "location": loc_str,
                "display": f"{full_name} ({u.email})" if full_name else u.email,
            })

        return JsonResponse({"results": results})

    def season_venues_view(self, request):
        """Возвращает очные этапы и площадки для выбранного сезона в JSON."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        season_id = request.GET.get("season_id")
        data = get_seasons_venues_data()
        season_data = data.get(str(season_id)) or {}
        return JsonResponse(season_data)

    def _get_initial_user_data(self, request, obj=None):
        initial_user_id = None
        if obj and getattr(obj, "registration_id", None):
            initial_user_id = obj.registration.user_id
        elif request.GET.get("user"):
            try:
                initial_user_id = int(request.GET.get("user"))
            except (ValueError, TypeError):
                pass

        if initial_user_id:
            try:
                u = User.objects.select_related("profile").get(pk=initial_user_id)
                prof = getattr(u, "profile", None)
                full_name = prof.full_name if prof else ""
                grade_str = f"{prof.grade} класс" if (prof and prof.grade) else ""
                loc_parts = filter(None, [getattr(prof, "city", None), getattr(prof, "school", None)])
                return {
                    "id": u.pk,
                    "email": u.email,
                    "full_name": full_name or "",
                    "has_name": bool(full_name),
                    "grade": grade_str,
                    "location": ", ".join(loc_parts),
                    "display": f"{full_name} ({u.email})" if full_name else u.email,
                }
            except User.DoesNotExist:
                pass
        return None

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        seasons_data = get_seasons_venues_data()
        extra_context["venues_by_season"] = seasons_data
        extra_context["venues_by_season_json"] = json.dumps(seasons_data, ensure_ascii=False)
        initial_user = self._get_initial_user_data(request)
        if initial_user:
            extra_context["initial_user_data"] = initial_user
            extra_context["initial_user_data_json"] = json.dumps(initial_user, ensure_ascii=False)
        extra_context["search_participants_url"] = reverse("admin:participation_venuebooking_search_participants")
        extra_context["season_venues_url"] = reverse("admin:participation_venuebooking_season_venues")
        return super().add_view(request, form_url, extra_context=extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        seasons_data = get_seasons_venues_data()
        extra_context["venues_by_season"] = seasons_data
        extra_context["venues_by_season_json"] = json.dumps(seasons_data, ensure_ascii=False)
        try:
            obj = self.get_object(request, object_id)
            initial_user = self._get_initial_user_data(request, obj=obj)
            if initial_user:
                extra_context["initial_user_data"] = initial_user
                extra_context["initial_user_data_json"] = json.dumps(initial_user, ensure_ascii=False)
        except Exception:
            pass
        extra_context["search_participants_url"] = reverse("admin:participation_venuebooking_search_participants")
        extra_context["season_venues_url"] = reverse("admin:participation_venuebooking_season_venues")
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def response_add(self, request, obj, post_url_continue=None):
        profile = getattr(obj.registration.user, "profile", None)
        user_name = profile.full_name if (profile and profile.full_name) else obj.registration.user.email
        self.message_user(
            request,
            format_html(
                'Участник <b>{}</b> успешно записан(а) на точку «<b>{}</b>» (этап «{}», сезон «{}»).',
                user_name,
                obj.venue.title,
                obj.stage.title,
                obj.stage.season.title,
            ),
            level=messages.SUCCESS,
        )
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        profile = getattr(obj.registration.user, "profile", None)
        user_name = profile.full_name if (profile and profile.full_name) else obj.registration.user.email
        self.message_user(
            request,
            format_html(
                'Запись участника <b>{}</b> обновлена: точка «<b>{}</b>» (этап «{}», сезон «{}»).',
                user_name,
                obj.venue.title,
                obj.stage.title,
                obj.stage.season.title,
            ),
            level=messages.SUCCESS,
        )
        return super().response_change(request, obj)

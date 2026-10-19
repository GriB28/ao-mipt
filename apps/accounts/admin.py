from pathlib import Path

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.participation.models import Registration
from apps.seasons.models import Season

from .emails import send_consent_rejected
from .forms import ConsentDocumentAddForm
from .models import ConsentDocument, OrganizerProfile, ParticipantProfile, StaffUser, User


class AdminsOnly:
    """Паспортные данные и сканы согласий — только администраторам.

    Организатору могут выдать доступ в админку (is_staff и группы) для
    площадок и задач. Сюда его права не распространяются, даже если в
    группе случайно отмечены права на анкеты.
    """

    def _allowed(self, request):
        return request.user.is_active and request.user.is_admin

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request, *args):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)


class ParticipantConsentAdminMixin:
    """Отображение статуса согласия и кнопка быстрой загрузки скана."""

    @admin.display(description="Скан согласия")
    def consent_summary(self, obj):
        if not obj or not getattr(obj, "user_id", None):
            return "Сначала сохраните анкету."
        consent = obj.user.latest_consent
        add_url = reverse("admin:accounts_consentdocument_add") + f"?user={obj.user_id}"
        if not consent:
            return format_html(
                '<span>Скан ещё не загружен.</span> &nbsp; '
                '<a class="button" href="{}">Загрузить скан согласия</a>',
                add_url,
            )
        color = {
            "approved": "#15803d",
            "pending": "#b45309",
            "rejected": "#b91c1c",
            "outdated": "#6b7280",
        }.get(consent.status, "#000")
        view_url = reverse("admin:accounts_consentdocument_change", args=[consent.pk])
        return format_html(
            '<b style="color:{}">● {}</b> &nbsp; '
            '<a href="{}" target="_blank" rel="noopener">{}</a> &nbsp; '
            '(<a href="{}">открыть в админке</a>) &nbsp; '
            '<a class="button" href="{}">Загрузить новый скан</a>',
            color,
            consent.get_status_display(),
            consent.get_absolute_url(),
            consent.filename,
            view_url,
            add_url,
        )


PROFILE_FIELDSETS = (
    ("Участник", {"fields": ("last_name", "first_name", "middle_name", "birth_date", "birth_place",
                             "grade", "school", "city", "region", "phone", "telegram")}),
    ("Документ и адрес", {"fields": ("doc_type", "doc_series", "doc_number", "doc_issued_at",
                                     "doc_issued_by", "doc_division_code", "reg_address")}),
    ("Согласие при регистрации", {"fields": ("consent_given", "consent_given_at",
                                             "consent_version")}),
    ("Скан согласия на обработку ПД", {"fields": ("consent_summary",)}),
)


class ProfileInline(ParticipantConsentAdminMixin, AdminsOnly, admin.StackedInline):
    model = ParticipantProfile
    can_delete = False
    extra = 0
    fieldsets = PROFILE_FIELDSETS
    readonly_fields = ("consent_summary",)


class ConsentInline(AdminsOnly, admin.TabularInline):
    model = ConsentDocument
    fk_name = "user"
    extra = 0
    fields = ("scan_link", "status", "for_minor", "created_at", "reviewed_by", "reviewed_at")
    readonly_fields = ("scan_link", "for_minor", "created_at", "reviewed_by", "reviewed_at")
    can_delete = False
    show_change_link = True

    @admin.display(description="скан")
    def scan_link(self, obj):
        if not obj.pk:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>',
                           obj.get_absolute_url(), obj.filename)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(AdminsOnly, BaseUserAdmin):
    """Учётки — только администраторам: иначе организатор с правом менять
    пользователей мог бы выдать себе роль администратора или суперпользователя."""

    list_display = ("email", "get_full_name", "role", "email_confirmed", "is_active")
    list_filter = ("role", "is_active", "email_confirmed", "is_staff")
    search_fields = (
        "email",
        "profile__last_name", "profile__first_name",
        "organizer_profile__last_name", "organizer_profile__first_name",
    )
    ordering = ("email",)
    inlines = [ProfileInline, ConsentInline]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Роль и доступ", {"fields": ("role", "email_confirmed", "is_active", "is_staff", "is_superuser", "groups")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")}),
    )


class HasVenueFilter(admin.SimpleListFilter):
    title = "наличие площадки"
    parameter_name = "has_venue"

    def lookups(self, request, model_admin):
        return [
            ("yes", "Есть площадка"),
            ("no", "Нет площадки"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(managed_venues__isnull=False).distinct()
        if self.value() == "no":
            return queryset.filter(managed_venues__isnull=True)
        return queryset


class OrganizerProfileInline(AdminsOnly, admin.StackedInline):
    model = OrganizerProfile
    can_delete = False
    extra = 0


@admin.register(StaffUser)
class StaffUserAdmin(UserAdmin):
    """Список администраторов и организаторов с информацией о площадках и задачах."""

    list_display = (
        "email",
        "role",
        "has_venue",
        "authored_problems_count",
        "reviewed_problems_count",
    )
    list_display_links = ("email",)
    list_filter = ("role", HasVenueFilter, "is_active")
    inlines = [OrganizerProfileInline, ProfileInline, ConsentInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                models.Q(role__in=[User.Role.ADMIN, User.Role.ORGANIZER])
                | models.Q(is_superuser=True)
                | models.Q(managed_venues__isnull=False)
            )
            .distinct()
            .annotate(
                venue_count=models.Count("managed_venues", distinct=True),
                authored_problems_count=models.Count("authored_problems", distinct=True),
                reviewed_problems_count=models.Count("reviewed_problems", distinct=True),
            )
        )

    @admin.display(description="наличие площадки", boolean=True, ordering="venue_count")
    def has_venue(self, obj):
        if hasattr(obj, "venue_count"):
            return obj.venue_count > 0
        return obj.managed_venues.exists()

    @admin.display(description="сколько задач написал", ordering="authored_problems_count")
    def authored_problems_count(self, obj):
        if hasattr(obj, "authored_problems_count"):
            return obj.authored_problems_count
        return obj.authored_problems.count()

    @admin.display(description="сколько задач для проверки на него записано", ordering="reviewed_problems_count")
    def reviewed_problems_count(self, obj):
        if hasattr(obj, "reviewed_problems_count"):
            return obj.reviewed_problems_count
        return obj.reviewed_problems.count()

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("role", User.Role.ORGANIZER)
        return initial

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "role":
            kwargs["choices"] = [
                (User.Role.ORGANIZER, "Организатор"),
                (User.Role.ADMIN, "Администратор"),
            ]
        return super().formfield_for_choice_field(db_field, request, **kwargs)


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(AdminsOnly, admin.ModelAdmin):
    list_display = ("full_name", "user", "phone", "telegram")
    search_fields = ("last_name", "first_name", "user__email")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.exclude(role=User.Role.PARTICIPANT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ParticipantProfile)
class ParticipantProfileAdmin(ParticipantConsentAdminMixin, AdminsOnly, admin.ModelAdmin):
    list_display = ("full_name", "user", "grade", "school", "city", "complete", "consent_status", "book_link")
    list_filter = ("grade", "region")
    search_fields = ("last_name", "first_name", "school", "user__email")
    fieldsets = PROFILE_FIELDSETS
    readonly_fields = ("consent_summary",)

    @admin.display(description="запись на точку")
    def book_link(self, obj):
        if not obj or not getattr(obj, "user_id", None):
            return "—"
        url = reverse("admin:participation_venuebooking_add") + f"?user={obj.user_id}"
        return format_html('<a class="button" style="padding: 2px 8px; font-size: 11px;" href="{}">+ Записать</a>', url)

    @admin.display(description="анкета заполнена", boolean=True)
    def complete(self, obj):
        return obj.is_complete

    @admin.display(description="согласие")
    def consent_status(self, obj):
        if not obj or not getattr(obj, "user_id", None):
            return "—"
        consent = obj.user.latest_consent
        if not consent:
            add_url = reverse("admin:accounts_consentdocument_add") + f"?user={obj.user_id}"
            return format_html('<span style="color:#b91c1c">нет</span> (<a href="{}">загрузить</a>)', add_url)
        color = {
            "approved": "#15803d",
            "pending": "#b45309",
            "rejected": "#b91c1c",
            "outdated": "#6b7280",
        }.get(consent.status, "#000")
        view_url = reverse("admin:accounts_consentdocument_change", args=[consent.pk])
        return format_html('<a href="{}" style="color:{}; font-weight:600;">● {}</a>',
                           view_url, color, consent.get_status_display())


class ConsentReviewForm(forms.ModelForm):
    class Meta:
        model = ConsentDocument
        fields = ("status", "review_comment")

    def clean(self):
        cleaned = super().clean()
        # Без объяснения участник не поймёт, что переделать.
        if cleaned.get("status") == ConsentDocument.Status.REJECTED \
                and not (cleaned.get("review_comment") or "").strip():
            self.add_error("review_comment", "Напишите участнику, что не так со сканом.")
        return cleaned


@admin.register(ConsentDocument)
class ConsentDocumentAdmin(AdminsOnly, admin.ModelAdmin):
    """
    Проверка и ручное добавление сканов согласий.

    - Проверка: открыть скан → сверить с данными анкеты справа → «Принять» или
      статус «Нужно переслать» с комментарием: участнику уйдёт письмо,
      а в кабинете появится просьба загрузить заново.
    - Ручное добавление: если у участника возникли проблемы с загрузкой в кабинете,
      администратор может загрузить скан за него — участие и запись на площадку
      открываются сразу же.
    """

    form = ConsentReviewForm
    add_form = ConsentDocumentAddForm
    list_display = ("participant", "user", "status", "for_minor", "created_at", "scan")
    list_filter = ("status", "for_minor")
    search_fields = ("user__email", "user__profile__last_name", "user__profile__first_name")
    autocomplete_fields = ("user",)
    date_hierarchy = "created_at"
    actions = ["approve"]
    readonly_fields = ("user", "scan", "for_minor", "data_table", "created_at",
                       "reviewed_by", "reviewed_at")
    fields = ("user", "scan", "for_minor", "data_table", "created_at",
              "status", "review_comment", "reviewed_by", "reviewed_at")

    def get_form(self, request, obj=None, change=False, **kwargs):
        if obj is None:
            kwargs["form"] = self.add_form
        return super().get_form(request, obj, change=change, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("user", "file", "status", "confirm_email", "review_comment")
        return self.fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.readonly_fields

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        if "user" in request.GET:
            initial["user"] = request.GET["user"]
        return initial

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            kwargs["queryset"] = User.objects.filter(role=User.Role.PARTICIPANT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="участник")
    def participant(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.full_name if profile else obj.user.email

    @admin.display(description="скан")
    def scan(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>',
                           obj.get_absolute_url(), obj.filename)

    @admin.display(description="данные, вписанные в бланк")
    def data_table(self, obj):
        labels = {f.name: f.verbose_name for f in ParticipantProfile._meta.get_fields()
                  if hasattr(f, "verbose_name")}
        rows = [(labels.get(k, k), v) for k, v in (obj.data or {}).items() if v]
        return format_html("<table>{}</table>", format_html("".join(
            format_html("<tr><th>{}</th><td>{}</td></tr>", k, v) for k, v in rows)))

    @admin.action(description="Принять выбранные согласия")
    def approve(self, request, queryset):
        updated = queryset.exclude(status=ConsentDocument.Status.OUTDATED).update(
            status=ConsentDocument.Status.APPROVED, reviewed_by=request.user,
            reviewed_at=timezone.now())
        self.message_user(request, f"Принято согласий: {updated}.")

    def save_model(self, request, obj, form, change):
        if not change:
            if form.cleaned_data.get("confirm_email") and not obj.user.email_confirmed:
                obj.user.email_confirmed = True
                obj.user.save(update_fields=["email_confirmed"])

            if not obj.original_name and obj.file:
                obj.original_name = Path(getattr(obj.file, "name", "")).name.rsplit("/", 1)[-1][:255]

            profile, _ = ParticipantProfile.objects.get_or_create(user=obj.user)
            if not obj.data:
                obj.data = profile.consent_data()
            obj.for_minor = profile.is_minor

            if obj.status == ConsentDocument.Status.APPROVED:
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()

            season = Season.objects.active()
            if season and obj.user.is_participant:
                reg, _ = Registration.objects.get_or_create(user=obj.user, season=season)
                if profile.grade and not reg.grade:
                    reg.grade = profile.grade
                    reg.save(update_fields=["grade"])
        else:
            status_changed = "status" in form.changed_data
            if status_changed:
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()

        super().save_model(request, obj, form, change)

        if obj.grants_access and hasattr(obj.user, "profile"):
            profile = obj.user.profile
            if not profile.consent_given:
                profile.consent_given = True
                profile.consent_given_at = timezone.now()
                profile.save(update_fields=["consent_given", "consent_given_at"])

        if obj.status == ConsentDocument.Status.REJECTED:
            if not change or "status" in form.changed_data:
                send_consent_rejected(request, obj)
                messages.info(request, f"Участнику отправлено письмо на {obj.user.email}.")

    def response_add(self, request, obj, post_url_continue=None):
        response = super().response_add(request, obj, post_url_continue)
        blockers = obj.user.participation_blockers()
        if blockers:
            self.message_user(
                request,
                f"Внимание: у участника {obj.user.email} ещё не выполнены шаги: {', '.join(blockers)}. "
                "Запись на площадки откроется после их выполнения.",
                level=messages.WARNING,
            )
        else:
            self.message_user(
                request,
                f"Участник {obj.user.email} теперь полностью допущен к олимпиаде (запись на площадки открыта).",
                level=messages.SUCCESS,
            )
        return response

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html

from .emails import send_consent_rejected
from .models import ConsentDocument, OrganizerProfile, ParticipantProfile, User


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


PROFILE_FIELDSETS = (
    ("Участник", {"fields": ("last_name", "first_name", "middle_name", "birth_date",
                             "grade", "school", "city", "region", "phone", "telegram")}),
    ("Документ и адрес", {"fields": ("doc_type", "doc_series", "doc_number", "doc_issued_at",
                                     "doc_issued_by", "reg_address")}),
    ("Законный представитель", {"fields": (
        "parent_last_name", "parent_first_name", "parent_middle_name", "parent_doc_type",
        "parent_doc_series", "parent_doc_number", "parent_doc_issued_at",
        "parent_doc_issued_by", "parent_reg_address")}),
    ("Согласие при регистрации", {"fields": ("consent_given", "consent_given_at",
                                             "consent_version")}),
)


class ProfileInline(AdminsOnly, admin.StackedInline):
    model = ParticipantProfile
    can_delete = False
    extra = 0
    fieldsets = PROFILE_FIELDSETS


@admin.register(User)
class UserAdmin(AdminsOnly, BaseUserAdmin):
    """Учётки — только администраторам: иначе организатор с правом менять
    пользователей мог бы выдать себе роль администратора или суперпользователя."""

    list_display = ("email", "get_full_name", "role", "email_confirmed", "is_active")
    list_filter = ("role", "is_active", "email_confirmed", "is_staff")
    search_fields = ("email", "profile__last_name", "profile__first_name")
    ordering = ("email",)
    inlines = [ProfileInline]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Роль и доступ", {"fields": ("role", "email_confirmed", "is_active", "is_staff", "is_superuser", "groups")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role")}),
    )


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(AdminsOnly, admin.ModelAdmin):
    list_display = ("full_name", "user", "phone", "telegram")
    search_fields = ("last_name", "first_name", "user__email")


@admin.register(ParticipantProfile)
class ParticipantProfileAdmin(AdminsOnly, admin.ModelAdmin):
    list_display = ("full_name", "user", "grade", "school", "city", "complete")
    list_filter = ("grade", "region")
    search_fields = ("last_name", "first_name", "school", "user__email")
    fieldsets = PROFILE_FIELDSETS

    @admin.display(description="анкета заполнена", boolean=True)
    def complete(self, obj):
        return obj.is_complete


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
    Проверка сканов согласий.

    Открыть скан → сверить с данными анкеты справа → «Принять» или
    статус «Нужно переслать» с комментарием: участнику уйдёт письмо,
    а в кабинете появится просьба загрузить заново.
    """

    form = ConsentReviewForm
    list_display = ("participant", "user", "status", "for_minor", "created_at", "scan")
    list_filter = ("status", "for_minor")
    search_fields = ("user__email", "user__profile__last_name", "user__profile__first_name")
    date_hierarchy = "created_at"
    actions = ["approve"]
    readonly_fields = ("user", "scan", "for_minor", "data_table", "created_at",
                       "reviewed_by", "reviewed_at")
    fields = ("user", "scan", "for_minor", "data_table", "created_at",
              "status", "review_comment", "reviewed_by", "reviewed_at")

    def has_add_permission(self, request, *args):
        # Сканы загружают сами участники в кабинете.
        return False

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
        status_changed = "status" in form.changed_data
        if status_changed:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
        if status_changed and obj.status == ConsentDocument.Status.REJECTED:
            send_consent_rejected(request, obj)
            messages.info(request, f"Участнику отправлено письмо на {obj.user.email}.")

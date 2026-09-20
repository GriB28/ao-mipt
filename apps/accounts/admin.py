from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OrganizerProfile, ParticipantProfile, User


class ProfileInline(admin.StackedInline):
    model = ParticipantProfile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
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
class OrganizerProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "phone", "telegram")
    search_fields = ("last_name", "first_name", "user__email")


@admin.register(ParticipantProfile)
class ParticipantProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "grade", "school", "city", "consent_given")
    list_filter = ("grade", "region", "consent_given")
    search_fields = ("last_name", "first_name", "school", "user__email")

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Delivery, Newsletter
from .services import queue_newsletter, render_body


class NewsletterAdminForm(forms.ModelForm):
    class Meta:
        model = Newsletter
        fields = ("subject", "body", "audience", "season", "venue")

    def clean(self):
        cleaned_data = super().clean()
        audience = cleaned_data.get("audience")
        venue = cleaned_data.get("venue")
        season = cleaned_data.get("season")

        venue_audiences = (
            Newsletter.Audience.VENUE_PARTICIPANTS,
            Newsletter.Audience.VENUE_ORGANIZERS,
        )
        season_audiences = (
            Newsletter.Audience.SEASON_PARTICIPANTS,
            Newsletter.Audience.SEASON_SUBMITTED,
            Newsletter.Audience.SEASON_NOT_SUBMITTED,
            Newsletter.Audience.VENUE_BOOKED,
        )

        if audience in venue_audiences:
            if not venue:
                self.add_error("venue", "Для этой аудитории необходимо выбрать площадку.")
            cleaned_data["season"] = None
        elif audience in season_audiences:
            if not season:
                self.add_error("season", "Для этой аудитории необходимо выбрать сезон.")
            cleaned_data["venue"] = None
        else:
            cleaned_data["season"] = None
            cleaned_data["venue"] = None

        return cleaned_data


class DeliveryInline(admin.TabularInline):
    model = Delivery
    extra = 0
    can_delete = False
    fields = ("email", "status", "sent_at", "error")
    readonly_fields = fields
    max_num = 0  # показываем уже созданные, вручную не добавляем

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Newsletter)
class NewsletterAdmin(admin.ModelAdmin):
    """
    Рассылка участникам.

    Кнопка «Отправить рассылку» есть на странице каждой рассылки.
    По ней открывается подтверждение с числом получателей — так нельзя
    случайно разослать письмо тысяче школьников одним кликом.
    """

    form = NewsletterAdminForm
    list_display = ("subject", "audience", "season", "venue", "status", "progress", "created_at")
    list_filter = ("status", "audience", "season", "venue")
    search_fields = ("subject", "body")
    readonly_fields = ("status", "created_by", "queued_at", "finished_at",
                       "last_error", "progress", "recipients_preview")
    inlines = [DeliveryInline]

    fieldsets = (
        ("Письмо", {"fields": ("subject", "body")}),
        ("Кому", {"fields": ("audience", "season", "venue", "recipients_preview")}),
        ("Отправка", {"fields": ("status", "progress", "queued_at", "finished_at", "last_error")}),
    )

    @admin.display(description="получатели")
    def recipients_preview(self, obj):
        if not obj or not obj.pk:
            return "Сохраните рассылку, чтобы посчитать получателей."
        count = obj.recipients_count
        if count == 0:
            if obj.audience in (Newsletter.Audience.VENUE_PARTICIPANTS, Newsletter.Audience.VENUE_ORGANIZERS) and not obj.venue:
                hint = "Проверьте аудиторию и выбранную площадку."
            elif obj.audience in (
                Newsletter.Audience.SEASON_PARTICIPANTS,
                Newsletter.Audience.SEASON_SUBMITTED,
                Newsletter.Audience.SEASON_NOT_SUBMITTED,
                Newsletter.Audience.VENUE_BOOKED,
            ) and not obj.season:
                hint = "Проверьте аудиторию и выбранный сезон."
            else:
                hint = "Проверьте аудиторию, сезон или площадку."
            return format_html(
                '<strong style="color:#b3261e">0 получателей.</strong> {}',
                hint,
            )
        return format_html("<strong>{}</strong> получателей", count)

    @admin.display(description="прогресс")
    def progress(self, obj):
        if not obj.pk or obj.status == Newsletter.Status.DRAFT:
            return "—"
        total = obj.deliveries.count()
        if not total:
            return "—"
        failed = obj.failed_count
        text = f"{obj.sent_count} из {total}"
        if failed:
            return format_html('{} <span style="color:#b3261e">(ошибок: {})</span>', text, failed)
        return text

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    # --- кнопка «Отправить рассылку» --------------------------------------

    def get_urls(self):
        custom = [
            path(
                "<int:pk>/send/",
                self.admin_site.admin_view(self.send_view),
                name="mailing_newsletter_send",
            ),
        ]
        return custom + super().get_urls()

    def send_view(self, request, pk):
        newsletter = get_object_or_404(Newsletter, pk=pk)

        if not self.has_change_permission(request, newsletter):
            messages.error(request, "Недостаточно прав для отправки рассылки.")
            return redirect("admin:mailing_newsletter_changelist")

        if request.method == "POST":
            if newsletter.status in (Newsletter.Status.QUEUED, Newsletter.Status.SENDING):
                messages.warning(request, "Эта рассылка уже отправляется.")
            else:
                count = queue_newsletter(newsletter)
                if count:
                    messages.success(
                        request,
                        f"Рассылка поставлена в очередь: {count} получателей. "
                        f"Письма уходят порциями, статус обновляется на этой странице.",
                    )
                else:
                    messages.error(request, "Получателей не нашлось — рассылка не поставлена.")
            return redirect("admin:mailing_newsletter_change", pk)

        recipients = newsletter.get_recipients()
        sample_user = recipients.first()
        return render(request, "admin/mailing/newsletter/send_confirm.html", {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "newsletter": newsletter,
            "count": recipients.count(),
            "sample": recipients[:10],
            "preview": render_body(newsletter, sample_user) if sample_user else "",
            "title": "Отправка рассылки",
        })

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["send_url"] = reverse("admin:mailing_newsletter_send", args=[object_id])
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("email", "newsletter", "status", "sent_at")
    list_filter = ("status", "newsletter")
    search_fields = ("email",)
    readonly_fields = ("newsletter", "user", "email", "status", "error", "sent_at")

    def has_add_permission(self, request):
        return False

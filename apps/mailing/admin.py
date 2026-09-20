from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Delivery, Newsletter
from .services import queue_newsletter, render_body


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

    list_display = ("subject", "audience", "season", "status", "progress", "created_at")
    list_filter = ("status", "audience", "season")
    search_fields = ("subject", "body")
    readonly_fields = ("status", "created_by", "queued_at", "finished_at",
                       "last_error", "progress", "recipients_preview")
    inlines = [DeliveryInline]

    fieldsets = (
        ("Письмо", {"fields": ("subject", "body")}),
        ("Кому", {"fields": ("audience", "season", "recipients_preview")}),
        ("Отправка", {"fields": ("status", "progress", "queued_at", "finished_at", "last_error")}),
    )

    @admin.display(description="получатели")
    def recipients_preview(self, obj):
        if not obj or not obj.pk:
            return "Сохраните рассылку, чтобы посчитать получателей."
        count = obj.recipients_count
        if count == 0:
            return format_html(
                '<strong style="color:#b3261e">0 получателей.</strong> '
                "Проверьте аудиторию и выбранный сезон."
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

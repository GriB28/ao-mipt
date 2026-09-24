from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.files import protected_file_response
from apps.participation.models import Registration, VenueBooking
from apps.seasons.models import Season

from . import consent_pdf
from .emails import read_token, send_confirmation
from .forms import ConsentUploadForm, OrganizerProfileForm, ProfileForm, SignUpForm
from .models import ConsentDocument, ParticipantProfile, User


def signup(request):
    """Регистрация школьника."""
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Сразу отмечаем участие в текущем сезоне: без него нельзя
        # записаться на площадку и человек не попадёт в рассылки по сезону.
        season = Season.objects.active()
        if season:
            Registration.objects.get_or_create(user=user, season=season)
        login(request, user)
        send_confirmation(request, user)
        messages.success(
            request,
            "Регистрация завершена. Мы отправили письмо со ссылкой для подтверждения "
            "почты — проверьте входящие и папку «Спам». Чтобы участвовать, заполните "
            "анкету и загрузите согласие — всё здесь, в кабинете.",
        )
        return redirect("accounts:profile")
    return render(request, "accounts/signup.html", {"form": form})


def confirm_email(request, token):
    """Переход по ссылке из письма.

    Ссылку часто открывают в другом браузере, где человек не залогинен,
    поэтому подтверждение не требует входа — достаточно подписи в ссылке.
    """
    # Куда вернуть после подтверждения: в кабинет, если вход есть,
    # иначе на форму входа, где будет видно сообщение об успехе.
    back = "accounts:profile" if request.user.is_authenticated else "accounts:login"
    data = read_token(token)
    if not data:
        messages.error(request, "Ссылка устарела или испорчена. Запросите письмо заново в кабинете.")
        return redirect(back)

    user = User.objects.filter(pk=data["uid"]).first()
    # Если после отправки письма человек сменил адрес, старая ссылка
    # не должна подтверждать новый: сверяем адрес, зашитый в подпись.
    if not user or user.email != data["email"]:
        messages.error(request, "Ссылка не подходит к этой учётной записи.")
        return redirect(back)

    if not user.email_confirmed:
        user.email_confirmed = True
        user.save(update_fields=["email_confirmed"])
    messages.success(request, "Почта подтверждена, спасибо.")
    return redirect(back)


@login_required
def resend_confirmation(request):
    """Переотправить письмо: первое могло не дойти или потеряться."""
    if request.user.email_confirmed:
        messages.info(request, "Почта уже подтверждена.")
    else:
        send_confirmation(request, request.user)
        messages.success(request, f"Письмо отправлено повторно на {request.user.email}.")
    return redirect("accounts:profile")


@login_required
def profile(request):
    """Кабинет. Форма анкеты зависит от роли."""
    if request.user.role != User.Role.PARTICIPANT:
        return _manager_profile(request)

    profile_obj, _ = ParticipantProfile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, instance=profile_obj)
    if request.method == "POST" and form.is_valid():
        before = _saved_consent_data(profile_obj)
        profile_obj = form.save()
        _sync_registration_grade(request.user, profile_obj.grade)
        consent = request.user.latest_consent
        # Подписанный бланк содержит паспортные данные на момент подписи.
        # Поменялись они — бланк больше им не соответствует, нужен новый.
        if consent and consent.status != ConsentDocument.Status.OUTDATED \
                and before != profile_obj.consent_data():
            consent.status = ConsentDocument.Status.OUTDATED
            consent.save(update_fields=["status"])
            messages.warning(request, "Анкета сохранена. Данные в согласии изменились — "
                                      "скачайте новый бланк, подпишите и загрузите его ещё раз.")
        else:
            messages.success(request, "Анкета сохранена.")
        return redirect(reverse("accounts:profile") + "#consent")
    if request.method == "POST":
        # Форма длинная: на телефоне ошибка в середине не видна с первого экрана.
        messages.error(request, "Анкета не сохранена — проверьте поля, отмеченные красным.")

    return render(request, "accounts/profile.html", {
        "form": form, "profile": profile_obj, "my_booking": _current_booking(request.user),
        "blockers": request.user.participation_blockers(),
        "consent": request.user.latest_consent,
        "upload_form": ConsentUploadForm(),
    })


def _saved_consent_data(profile_obj):
    """Данные для бланка, как они лежат в базе (форма уже подменила поля в памяти)."""
    if not profile_obj.pk:
        return {}
    return ParticipantProfile.objects.get(pk=profile_obj.pk).consent_data()


def _sync_registration_grade(user, grade):
    """Класс в участии текущего сезона — по анкете: по нему строятся списки."""
    season = Season.objects.active()
    if season and grade:
        Registration.objects.filter(user=user, season=season).update(grade=grade)


def _manager_profile(request):
    instance = getattr(request.user, "organizer_profile", None)
    form = OrganizerProfileForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, "Анкета сохранена.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile_organizer.html", {"form": form, "profile": instance})


@login_required
def consent_blank(request):
    """PDF-бланк согласия, собранный из анкеты."""
    profile_obj = getattr(request.user, "profile", None)
    if profile_obj is None or not profile_obj.is_complete:
        messages.error(request, "Сначала заполните анкету целиком — из неё собирается бланк.")
        return redirect("accounts:profile")
    response = HttpResponse(consent_pdf.build(profile_obj), content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="soglasie-pd.pdf"'
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
@login_required
def consent_upload(request):
    """Скан подписанного согласия. Участие открывается сразу, проверка — вручную."""
    profile_obj = getattr(request.user, "profile", None)
    if profile_obj is None or not profile_obj.is_complete:
        messages.error(request, "Сначала заполните анкету и скачайте бланк согласия.")
        return redirect("accounts:profile")
    form = ConsentUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        for error in form.errors.get("file", []):
            messages.error(request, error)
        return redirect(reverse("accounts:profile") + "#consent")

    upload = form.cleaned_data["file"]
    with transaction.atomic():
        # Двойное нажатие не должно дать два скана подряд.
        User.objects.select_for_update().filter(pk=request.user.pk).first()
        if request.user.consents.count() >= settings.MAX_CONSENT_UPLOADS:
            messages.error(request, "Загружено слишком много сканов. Напишите организаторам.")
            return redirect(reverse("accounts:profile") + "#consent")
        ConsentDocument.objects.create(
            user=request.user, file=upload, original_name=Path(upload.name).name[:255],
            for_minor=profile_obj.is_minor, data=profile_obj.consent_data(),
        )
    messages.success(request, "Согласие загружено — участие открыто. Мы проверим скан вручную "
                              "и напишем на почту, если его понадобится переслать.")
    return redirect(reverse("accounts:profile") + "#consent")


@login_required
def consent_file(request, pk):
    """Скан согласия: только владельцу и администраторам. Там паспортные данные."""
    consent = get_object_or_404(ConsentDocument, pk=pk)
    if consent.user_id != request.user.pk and not request.user.is_admin:
        raise Http404
    return protected_file_response(request, consent.file, consent.filename)


def _current_booking(user):
    """Запись на очный тур текущего сезона — чтобы её было видно в кабинете."""
    season = Season.objects.active()
    if not season:
        return None
    return (VenueBooking.objects
            .filter(registration__user=user, stage__season=season)
            .exclude(status=VenueBooking.Status.CANCELLED)
            .select_related("venue").first())

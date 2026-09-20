from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.participation.models import Registration, VenueBooking
from apps.seasons.models import Season

from .emails import read_token, send_confirmation
from .forms import OrganizerProfileForm, ProfileForm, SignUpForm
from .models import User


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
            Registration.objects.get_or_create(
                user=user, season=season,
                defaults={"grade": form.cleaned_data.get("grade")},
            )
        login(request, user)
        send_confirmation(request, user)
        messages.success(
            request,
            "Регистрация завершена. Мы отправили письмо со ссылкой "
            "для подтверждения почты — проверьте входящие и папку «Спам».",
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
    if request.user.role == User.Role.ORGANIZER:
        instance = getattr(request.user, "organizer_profile", None)
        form_class, template = OrganizerProfileForm, "accounts/profile_organizer.html"
    else:
        instance = getattr(request.user, "profile", None)
        form_class, template = ProfileForm, "accounts/profile.html"

    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, "Анкета сохранена.")
        return redirect("accounts:profile")

    return render(request, template, {
        "form": form, "profile": instance, "my_booking": _current_booking(request.user),
    })


def _current_booking(user):
    """Запись на очный тур текущего сезона — чтобы её было видно в кабинете."""
    season = Season.objects.active()
    if not season:
        return None
    return (VenueBooking.objects
            .filter(registration__user=user, stage__season=season)
            .exclude(status=VenueBooking.Status.CANCELLED)
            .select_related("venue").first())

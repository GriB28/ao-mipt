"""
Письма про учётную запись: подтверждение адреса.

Подтверждение нужно по двум причинам. Первая — опечатка в почте при
регистрации иначе всплывёт только в апреле, когда участник не получит
вызов на финал. Вторая — рассылки: письма на несуществующие адреса
портят репутацию домена, и почтовики начинают класть в спам остальные.

Ссылка подписана (django.core.signing), а не хранится в базе отдельной
таблицей: подпись содержит id пользователя и время, проверяется без
запроса к базе и протухает сама через CONFIRM_MAX_AGE.
"""

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

#: Сколько живёт ссылка из письма. Неделя — чтобы письмо, прочитанное
#: после выходных, ещё работало.
CONFIRM_MAX_AGE = 7 * 24 * 60 * 60

SALT = "accounts.email-confirm"


def make_token(user) -> str:
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=SALT)


def read_token(token: str):
    """Вернуть данные из ссылки или None, если она битая или протухла."""
    try:
        return signing.loads(token, salt=SALT, max_age=CONFIRM_MAX_AGE)
    except signing.BadSignature:
        return None


def send_confirmation(request, user) -> None:
    """Отправить письмо со ссылкой подтверждения.

    В DEBUG письма печатаются в консоль (EMAIL_BACKEND=console), поэтому
    локально ссылку видно в том же терминале, где запущен runserver.
    """
    path = reverse("accounts:confirm_email", args=[make_token(user)])
    context = {
        "confirm_url": request.build_absolute_uri(path),
        "contact_email": settings.CONTACT_EMAIL,
        "days": CONFIRM_MAX_AGE // 86400,
    }
    send_mail(
        subject="Подтвердите почту — Аэрокосмическая олимпиада МФТИ",
        message=render_to_string("accounts/email_confirm.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        # Регистрация не должна падать из-за недоступного SMTP:
        # человек уже создан, письмо можно переотправить из кабинета.
        fail_silently=False,
    )


def send_consent_rejected(request, consent) -> None:
    """Письмо «пришлите согласие заново» с комментарием администратора."""
    context = {
        "comment": consent.review_comment,
        "profile_url": request.build_absolute_uri(reverse("accounts:profile") + "#consent"),
        "contact_email": settings.CONTACT_EMAIL,
    }
    send_mail(
        subject="Пришлите согласие заново — Аэрокосмическая олимпиада МФТИ",
        message=render_to_string("accounts/email_consent_rejected.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[consent.user.email],
        fail_silently=True,
    )

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Вход по e-mail без учёта регистра: Ivan@mail.ru == ivan@mail.ru."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        email = (username or kwargs.get("email") or "").strip()
        if not email:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Тратим то же время, что и на реальную проверку —
            # иначе по скорости ответа можно узнать, есть ли такой e-mail.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

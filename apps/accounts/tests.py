"""Регистрация и вход — через них проходит каждый участник."""

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .emails import make_token
from .models import ParticipantProfile, User


class SignUpTest(TestCase):
    form_data = {
        "email": "Vasya@Example.RU",
        "password1": "olymp12345",
        "password2": "olymp12345",
        "last_name": "Пупкин",
        "first_name": "Василий",
        "grade": 10,
        "school": "Школа №1",
        "city": "Москва",
        "region": "Москва",
        "telegram": "@vasya",
        "consent": "on",
    }

    def test_signup_creates_user_and_profile(self):
        response = self.client.post(reverse("accounts:signup"), self.form_data)
        self.assertRedirects(response, reverse("accounts:profile"))

        user = User.objects.get(email="vasya@example.ru")  # почта приводится к нижнему регистру
        self.assertEqual(user.role, User.Role.PARTICIPANT)

        profile = ParticipantProfile.objects.get(user=user)
        self.assertEqual(profile.last_name, "Пупкин")
        self.assertEqual(profile.region, "Москва")
        self.assertTrue(profile.consent_given)
        self.assertIsNotNone(profile.consent_given_at)

    def test_school_city_and_region_are_required(self):
        """Без них нельзя посчитать охват и разложить людей по площадкам."""
        for field in ("school", "city", "region"):
            with self.subTest(field=field):
                response = self.client.post(reverse("accounts:signup"), self.form_data | {field: ""})
                self.assertFormError(response.context["form"], field, "Обязательное поле.")
                self.assertFalse(User.objects.filter(email="vasya@example.ru").exists())

    def test_unknown_region_rejected(self):
        """Регион выбирается из списка, произвольную строку не принимаем."""
        self.client.post(reverse("accounts:signup"), self.form_data | {"region": "Мордор"})
        self.assertFalse(User.objects.filter(email="vasya@example.ru").exists())

    def test_phone_or_telegram_required(self):
        data = self.form_data | {"telegram": "", "phone": ""}
        response = self.client.post(reverse("accounts:signup"), data)
        self.assertFormError(response.context["form"], "phone",
                             "Укажите телефон или Telegram — хотя бы один способ связи.")
        self.assertFalse(User.objects.filter(email="vasya@example.ru").exists())

    def test_phone_alone_is_enough(self):
        data = self.form_data | {"telegram": "", "phone": "+7 900 000-00-00"}
        self.client.post(reverse("accounts:signup"), data)
        self.assertTrue(User.objects.filter(email="vasya@example.ru").exists())

    def test_signup_requires_consent(self):
        data = self.form_data | {"consent": ""}
        self.client.post(reverse("accounts:signup"), data)
        self.assertFalse(User.objects.filter(email="vasya@example.ru").exists())

    def test_duplicate_email_rejected_regardless_of_case(self):
        User.objects.create_user("vasya@example.ru", "olymp12345")
        self.client.post(reverse("accounts:signup"), self.form_data)
        self.assertEqual(User.objects.filter(email__iexact="vasya@example.ru").count(), 1)

    def test_short_password_rejected(self):
        data = self.form_data | {"password1": "123", "password2": "123"}
        self.client.post(reverse("accounts:signup"), data)
        self.assertFalse(User.objects.filter(email="vasya@example.ru").exists())


class EmailConfirmTest(TestCase):
    """Подтверждение почты: опечатка в адресе иначе всплывёт только в апреле."""

    def _signup(self):
        self.client.post(reverse("accounts:signup"), SignUpTest.form_data)
        return User.objects.get(email="vasya@example.ru")

    def test_signup_sends_letter_with_link(self):
        user = self._signup()
        self.assertEqual(len(mail.outbox), 1)
        # Сам токен не сверяем: он содержит метку времени и у двух вызовов
        # совпадёт только в пределах одной секунды.
        self.assertIn("/accounts/confirm/", mail.outbox[0].body)
        self.assertFalse(user.email_confirmed)

    def test_link_confirms_email(self):
        user = self._signup()
        self.client.get(reverse("accounts:confirm_email", args=[make_token(user)]))
        user.refresh_from_db()
        self.assertTrue(user.email_confirmed)

    def test_broken_link_confirms_nothing(self):
        user = self._signup()
        self.client.get(reverse("accounts:confirm_email", args=["not-a-token"]))
        user.refresh_from_db()
        self.assertFalse(user.email_confirmed)

    def test_link_stops_working_after_email_change(self):
        """Иначе ссылкой со старого адреса можно подтвердить новый."""
        user = self._signup()
        token = make_token(user)
        user.email = "other@example.ru"
        user.save(update_fields=["email"])

        self.client.get(reverse("accounts:confirm_email", args=[token]))
        user.refresh_from_db()
        self.assertFalse(user.email_confirmed)

    def test_resend_requires_login(self):
        response = self.client.get(reverse("accounts:resend_confirmation"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class LoginTest(TestCase):
    def setUp(self):
        User.objects.create_user("ivan@example.ru", "olymp12345")

    def test_login_is_case_insensitive(self):
        ok = self.client.login(username="IVAN@example.RU", password="olymp12345")
        self.assertTrue(ok)

    def test_login_fails_with_wrong_password(self):
        self.assertFalse(self.client.login(username="ivan@example.ru", password="nope"))

    def test_login_fails_for_unknown_email(self):
        self.assertFalse(self.client.login(username="nobody@example.ru", password="olymp12345"))


class OrganizerAccessTest(TestCase):
    """Организаторов заводит администратор — самостоятельной регистрации нет."""

    def test_no_public_organizer_signup(self):
        self.assertEqual(self.client.get("/accounts/signup/organizer/").status_code, 404)

    def test_participant_cannot_add_venue(self):
        user = User.objects.create_user("kid@e.ru", "olymp12345")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("venues:apply")).status_code, 403)

    def test_organizer_can_open_venue_form(self):
        user = User.objects.create_user("org@e.ru", "olymp12345", role=User.Role.ORGANIZER)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("venues:apply")).status_code, 200)

    def test_organizer_role_grants_no_admin_access(self):
        user = User.objects.create_user("org2@e.ru", "olymp12345", role=User.Role.ORGANIZER)
        self.client.force_login(user)
        self.assertFalse(user.is_staff)
        self.assertEqual(self.client.get("/admin/").status_code, 302)


class ConsentTest(TestCase):
    def test_signup_page_links_to_consent_documents(self):
        html = self.client.get(reverse("accounts:signup")).content.decode()
        self.assertIn(reverse("content:page", args=["consent"]), html)
        self.assertIn(reverse("content:page", args=["privacy"]), html)

"""Регистрация и вход — через них проходит каждый участник."""

import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .emails import make_token
from .models import ConsentDocument, ParticipantProfile, User


class SignUpTest(TestCase):
    """Регистрация — только почта и пароль, анкета потом."""

    form_data = {
        "email": "Vasya@Example.RU",
        "password1": "olymp12345",
        "password2": "olymp12345",
    }

    def test_signup_creates_user_and_empty_profile(self):
        response = self.client.post(reverse("accounts:signup"), self.form_data)
        # Не входим: кабинет — только после подтверждения почты.
        self.assertRedirects(response, reverse("accounts:signup_done"))
        self.assertNotIn("_auth_user_id", self.client.session)

        user = User.objects.get(email="vasya@example.ru")  # почта приводится к нижнему регистру
        self.assertEqual(user.role, User.Role.PARTICIPANT)
        profile = ParticipantProfile.objects.get(user=user)
        self.assertFalse(profile.is_complete)
        self.assertFalse(user.can_participate)

    def test_signup_asks_nothing_but_email_and_password(self):
        html = self.client.get(reverse("accounts:signup")).content.decode()
        for field in ("last_name", "school", "doc_number"):
            self.assertNotIn(f'name="{field}"', html)

    def test_signup_has_no_consent_checkboxes(self):
        """Согласие — подписанным бланком из кабинета, не галочкой при регистрации."""
        html = self.client.get(reverse("accounts:signup")).content.decode()
        self.assertNotIn('type="checkbox"', html)

    def test_duplicate_email_rejected_regardless_of_case(self):
        User.objects.create_user("vasya@example.ru", "olymp12345")
        self.client.post(reverse("accounts:signup"), self.form_data)
        self.assertEqual(User.objects.filter(email__iexact="vasya@example.ru").count(), 1)

    def test_short_password_rejected(self):
        data = self.form_data | {"password1": "123", "password2": "123"}
        self.client.post(reverse("accounts:signup"), data)
        self.assertFalse(User.objects.filter(email="vasya@example.ru").exists())


def profile_data(**extra):
    """Полная анкета несовершеннолетнего — как её отправляет форма.

    Даты — тремя списками (число, месяц, год), серия и номер — отдельно.
    """
    return {
        "last_name": "Пупкин", "first_name": "Василий", "middle_name": "",
        "birth_date_day": "1", "birth_date_month": "5", "birth_date_year": "2010",
        "doc_type": "passport_rf", "doc_series": "4510", "doc_number": "123456",
        "doc_issued_at_day": "1", "doc_issued_at_month": "6", "doc_issued_at_year": "2024",
        "doc_issued_by": "ГУ МВД России по г. Москве",
        "reg_address": "101000, Москва, ул. Мира, 1", "grade": "10", "school": "Школа № 1",
        "city": "Москва", "region": "Москва", "phone": "+7 900 123-45-67", "telegram": "",
        "parent_last_name": "Пупкина", "parent_first_name": "Мария", "parent_middle_name": "",
        "parent_doc_type": "passport_rf", "parent_doc_series": "4500", "parent_doc_number": "654321",
        "parent_doc_issued_at_day": "1", "parent_doc_issued_at_month": "1",
        "parent_doc_issued_at_year": "2012", "parent_doc_issued_by": "ОВД Тверской",
        "parent_reg_address": "101000, Москва, ул. Мира, 1",
    } | extra


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="olymp-test-media-"))
class ParticipationStepsTest(TestCase):
    """Почта → анкета → согласие: после этого открыто участие."""

    def setUp(self):
        self.user = User.objects.create_user("kid@e.ru", "olymp12345", email_confirmed=True)
        ParticipantProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def _save_profile(self, **extra):
        return self.client.post(reverse("accounts:profile"), profile_data(**extra))

    def _upload(self, name="scan.jpg", content=b"\xff\xd8 scan", **extra):
        f = SimpleUploadedFile(name, content, content_type="image/jpeg")
        return self.client.post(reverse("accounts:consent_upload"), {"file": f} | extra)

    def test_full_path_opens_participation(self):
        self.assertFalse(self.user.can_participate)
        self._save_profile()
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile.is_complete)
        self.assertFalse(self.user.can_participate)  # согласия ещё нет

        blank = self.client.get(reverse("accounts:consent_blank"))
        self.assertEqual(blank["Content-Type"], "application/pdf")
        self.assertTrue(blank.content.startswith(b"%PDF"))

        self._upload()
        consent = ConsentDocument.objects.get(user=self.user)
        self.assertEqual(consent.status, ConsentDocument.Status.PENDING)
        self.assertTrue(consent.for_minor)
        self.assertEqual((consent.data["doc_series"], consent.data["doc_number"]), ("4510", "123456"))
        self.assertTrue(User.objects.get(pk=self.user.pk).can_participate)

    def test_passport_series_and_number_are_checked(self):
        response = self._save_profile(doc_series="12", doc_number="12345")
        self.assertFormError(response.context["form"], "doc_series", "Серия паспорта — 4 цифры.")
        self.assertFormError(response.context["form"], "doc_number", "Номер паспорта — 6 цифр.")
        self._save_profile(doc_series="45 10", doc_number="123 456")
        profile = ParticipantProfile.objects.get(user=self.user)
        self.assertEqual((profile.doc_series, profile.doc_number), ("4510", "123456"))

    def test_birth_certificate_is_accepted(self):
        """У семиклассника паспорта нет — только свидетельство о рождении."""
        self._save_profile(doc_type="birth_cert", doc_series="iv-мю", doc_number="123456",
                           birth_date_year="2013", grade="7", doc_issued_at_year="2013")
        profile = ParticipantProfile.objects.get(user=self.user)
        self.assertTrue(profile.is_complete)
        self.assertEqual(profile.doc_series, "IV-МЮ")

    def test_foreign_document_may_have_no_series(self):
        self._save_profile(doc_type="foreign", doc_series="", doc_number="N1234567")
        self.assertTrue(ParticipantProfile.objects.get(user=self.user).is_complete)

    def test_dates_are_day_month_year(self):
        html = self.client.get(reverse("accounts:profile")).content.decode()
        day, month, year = (html.index(f'name="birth_date_{part}"') for part in ("day", "month", "year"))
        self.assertLess(day, month)
        self.assertLess(month, year)
        # И подписи стоят у своих списков.
        self.assertIn('>число</option>', html[day:month])
        self.assertIn('>год</option>', html[year:])

    def test_parent_is_required_for_minor_only(self):
        no_parent = {k: "" for k in profile_data() if k.startswith("parent_")}
        response = self._save_profile(**no_parent)
        self.assertFormError(response.context["form"], "parent_last_name",
                             "Нужно, если участнику нет 18 лет.")
        self.assertFalse(ParticipantProfile.objects.get(user=self.user).is_complete)

        self._save_profile(**no_parent, birth_date_year="2006", grade="11")
        profile = ParticipantProfile.objects.get(user=self.user)
        self.assertFalse(profile.is_minor)
        self.assertTrue(profile.is_complete)

    def test_parent_passport_is_checked_too(self):
        response = self._save_profile(parent_doc_series="45", parent_doc_number="1")
        self.assertFormError(response.context["form"], "parent_doc_series", "Серия паспорта — 4 цифры.")
        self.assertFormError(response.context["form"], "parent_doc_number", "Номер паспорта — 6 цифр.")

    def test_no_blank_until_profile_is_complete(self):
        response = self.client.get(reverse("accounts:consent_blank"))
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_scan_over_the_limit_is_rejected(self):
        self._save_profile()
        with self.settings(PARTICIPANT_UPLOAD_MAX_MB=0.001):
            self._upload(content=b"x" * 5000)
        self.assertFalse(ConsentDocument.objects.exists())

    def test_scan_must_be_pdf_or_picture(self):
        self._save_profile()
        self._upload(name="scan.docx")
        self.assertFalse(ConsentDocument.objects.exists())

    def test_changing_passport_data_requires_new_consent(self):
        self._save_profile()
        self._upload()
        self._save_profile(phone="+7 900 765-43-21")  # телефона в бланке нет
        self.assertEqual(ConsentDocument.objects.get().status, ConsentDocument.Status.PENDING)
        self._save_profile(doc_number="999999")
        self.assertEqual(ConsentDocument.objects.get().status, ConsentDocument.Status.OUTDATED)
        self.assertFalse(User.objects.get(pk=self.user.pk).can_participate)

    def test_rejected_consent_keeps_participation(self):
        """Пока участник досылает исправленное, он не выпадает из олимпиады."""
        self._save_profile()
        self._upload()
        ConsentDocument.objects.update(status=ConsentDocument.Status.REJECTED)
        self.assertTrue(User.objects.get(pk=self.user.pk).can_participate)

    def test_unconfirmed_email_blocks_participation(self):
        self._save_profile()
        self._upload()
        User.objects.filter(pk=self.user.pk).update(email_confirmed=False)
        self.assertIn("подтвердить почту по ссылке из письма",
                      User.objects.get(pk=self.user.pk).participation_blockers())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="olymp-test-media-"))
class ConsentAccessTest(TestCase):
    """Скан согласия и паспортные данные видят только сам участник и администраторы."""

    def setUp(self):
        from .testing import make_eligible

        self.kid = make_eligible(User.objects.create_user("kid@e.ru", "olymp12345"))
        self.consent = ConsentDocument.objects.get(user=self.kid)
        self.admin = User.objects.create_user("adm@e.ru", "olymp12345", role=User.Role.ADMIN,
                                              is_staff=True)
        self.organizer = User.objects.create_user("org@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER, is_staff=True)

    def test_owner_and_admin_open_the_scan(self):
        for user in (self.kid, self.admin):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.consent.get_absolute_url()).status_code, 200)

    def test_others_do_not(self):
        other = User.objects.create_user("other@e.ru", "olymp12345")
        for user in (other, self.organizer):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.consent.get_absolute_url()).status_code, 404)

    def test_organizer_in_admin_does_not_see_passport_data(self):
        """Даже с правами из группы: анкеты и согласия — только администраторам."""
        from django.contrib.auth.models import Permission

        self.organizer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="accounts"))
        self.client.force_login(self.organizer)
        for url in ("/admin/accounts/participantprofile/", "/admin/accounts/consentdocument/",
                    f"/admin/accounts/participantprofile/{self.kid.profile.pk}/change/"):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (302, 403, 404))
        # И учётки тоже: иначе можно было бы выдать себе роль администратора.
        self.assertEqual(self.client.get(f"/admin/accounts/user/{self.kid.pk}/change/").status_code, 403)
        self.client.post(f"/admin/accounts/user/{self.organizer.pk}/change/",
                         {"email": "org@e.ru", "role": "admin", "is_superuser": "on"})
        self.organizer.refresh_from_db()
        self.assertFalse(self.organizer.is_superuser)

    def test_admin_rejects_with_comment_and_participant_gets_a_letter(self):
        self.client.force_login(self.admin)
        url = f"/admin/accounts/consentdocument/{self.consent.pk}/change/"
        self.client.post(url, {"status": "rejected", "review_comment": ""})
        self.consent.refresh_from_db()
        self.assertEqual(self.consent.status, ConsentDocument.Status.PENDING)  # без комментария нельзя

        self.client.post(url, {"status": "rejected", "review_comment": "Нет подписи родителя"})
        self.consent.refresh_from_db()
        self.assertEqual(self.consent.status, ConsentDocument.Status.REJECTED)
        self.assertEqual(self.consent.reviewed_by, self.admin)
        self.assertEqual(mail.outbox[-1].to, ["kid@e.ru"])
        self.assertIn("Нет подписи родителя", mail.outbox[-1].body)


class ConsentPdfTest(TestCase):
    def _text(self, **fields):
        from . import consent_pdf
        from .testing import make_eligible

        kid = make_eligible(User.objects.create_user("kid@e.ru", "olymp12345"), **fields)
        return kid, consent_pdf.fill(consent_pdf.template_text(minor=kid.profile.is_minor),
                                     consent_pdf.values_for(kid.profile))

    def test_minor_blank_is_filled_with_parent_data(self):
        """От руки в бланке — только подписи: данные представителя из анкеты."""
        from . import consent_pdf

        kid, text = self._text(last_name="О'Нил")
        self.assertIn("О&#x27;Нил", text)  # данные экранированы для разметки reportlab
        self.assertIn("серия 0000 № 000000", text)
        self.assertIn("Я, Тестова Анна", text)
        self.assertIn("серия 0000 № 000001", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("_____", text)
        self.assertTrue(consent_pdf.build(kid.profile).startswith(b"%PDF"))

    def test_unknown_placeholder_becomes_a_blank_line(self):
        from . import consent_pdf

        self.assertEqual(consent_pdf.fill("Я, {{ parent_name }}.", {}),
                         f"Я, {consent_pdf.legal_templates.BLANK}.")

    def test_adult_blank_has_no_parent(self):
        from datetime import date

        _, text = self._text(birth_date=date(2000, 1, 1))
        self.assertNotIn("законного представителя", text)


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

    def _login(self):
        return self.client.post(reverse("accounts:login"),
                                {"username": "vasya@example.ru", "password": "olymp12345"})

    def test_no_login_before_confirmation(self):
        self._signup()
        response = self._login()
        self.assertContains(response, "Почта ещё не подтверждена")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_works_after_confirmation(self):
        user = self._signup()
        self.client.get(reverse("accounts:confirm_email", args=[make_token(user)]))
        self.assertRedirects(self._login(), reverse("core:home"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)

    def test_link_itself_does_not_log_in(self):
        """Пересланное письмо не должно давать доступ к кабинету."""
        user = self._signup()
        self.client.get(reverse("accounts:confirm_email", args=[make_token(user)]))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signing_up_again_resends_but_keeps_password(self):
        """Иначе чужую неподтверждённую регистрацию мог бы «перехватить» любой."""
        self._signup()
        self.client.post(reverse("accounts:signup"), SignUpTest.form_data | {
            "password1": "another-pass-777", "password2": "another-pass-777"})
        self.assertEqual(len(mail.outbox), 2)
        user = User.objects.get(email="vasya@example.ru")
        self.assertTrue(user.check_password("olymp12345"))

    def test_resend_does_not_reveal_who_is_registered(self):
        self._signup()
        answers = [self.client.post(reverse("accounts:resend_confirmation"), {"email": email},
                                    follow=True).content.decode().count("письмо со ссылкой уже в пути")
                   for email in ("vasya@example.ru", "nobody@example.ru")]
        self.assertEqual(answers, [1, 1])
        self.assertEqual(len(mail.outbox), 2)  # регистрация + повтор, чужому — ничего

    def test_password_reset_confirms_email(self):
        """Не нашёл письмо о регистрации, сбросил пароль — ящик доказан."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        user = self._signup()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        url = reverse("accounts:password_reset_confirm",
                      args=[uid, default_token_generator.make_token(user)])
        form_url = self.client.get(url)["Location"]
        self.client.post(form_url, {"new_password1": "fresh-pass-2026", "new_password2": "fresh-pass-2026"})
        user.refresh_from_db()
        self.assertTrue(user.email_confirmed)

    def test_staff_log_in_without_confirmation(self):
        """Организаторов заводит администратор — им подтверждать почту не нужно."""
        User.objects.create_user("org@example.ru", "olymp12345", role=User.Role.ORGANIZER)
        response = self.client.post(reverse("accounts:login"),
                                    {"username": "org@example.ru", "password": "olymp12345"})
        self.assertEqual(response.status_code, 302)

    def test_stale_unconfirmed_accounts_are_purged(self):
        from datetime import timedelta

        from django.core.management import call_command
        from django.utils import timezone

        user = self._signup()
        User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=15))
        confirmed = User.objects.create_user("ok@example.ru", "olymp12345", email_confirmed=True)
        User.objects.filter(pk=confirmed.pk).update(date_joined=timezone.now() - timedelta(days=15))
        call_command("purge_unconfirmed", verbosity=0)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(User.objects.filter(pk=confirmed.pk).exists())


class ProblemsNeedLoginTest(TestCase):
    """Задачи текущего тура — только вошедшим участникам с подтверждённой почтой."""

    def test_anonymous_sees_schedule_but_no_problems(self):
        from apps.contest.tests import open_problem

        call_command("seed_demo", verbosity=0)
        problem = open_problem()
        html = self.client.get(reverse("contest:problem_list")).content.decode()
        self.assertIn("Задачи видны зарегистрированным участникам", html)
        self.assertNotIn(problem.title, html)
        detail = self.client.get(reverse("contest:problem_detail", args=[problem.pk]))
        self.assertIn("/accounts/login/", detail["Location"])


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
    def test_signup_page_links_to_privacy_policy(self):
        html = self.client.get(reverse("accounts:signup")).content.decode()
        self.assertIn(reverse("content:page", args=["privacy"]), html)

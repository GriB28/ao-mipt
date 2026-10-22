"""Smoke-тесты: все публичные страницы отвечают 200."""

from django.test import TestCase
from django.urls import reverse


class PublicPagesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_public_pages_render(self):
        names = [
            "core:home",
            "accounts:login",
            "accounts:signup",
            "venues:map",
            "venues:geojson",
            "contest:problem_list",
            "content:news_list",
            "content:lecture_list",
            "content:lecture_archive",
            "content:problem_archive",
        ]
        for name in names:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_login_required_pages_redirect(self):
        for name in ["accounts:profile", "contest:my_submissions", "venues:apply"]:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_geojson_contains_only_approved_venues(self):
        from apps.venues.models import Venue

        Venue.objects.create(
            title="Скрытая школа", region="R", city="C", address="A",
            latitude=55.0, longitude=37.0, status=Venue.Status.PENDING,
        )
        data = self.client.get(reverse("venues:geojson")).json()
        titles = [f["properties"]["title"] for f in data["features"]]
        self.assertNotIn("Скрытая школа", titles)


class ExportStaticTest(TestCase):
    """Демо для коллег собирается одной командой — она не должна тихо ломаться."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def _export(self, **kwargs):
        import tempfile
        from io import StringIO
        from pathlib import Path

        from django.core.management import call_command

        out = Path(tempfile.mkdtemp()) / "dist"
        # Команда рассказывает о каждой странице — в тестах этот вывод лишний.
        call_command("export_static", out=str(out), stdout=StringIO(), **kwargs)
        return out

    def test_export_produces_linked_pages(self):
        out = self._export()
        for name in ["index.html", "online.html", "offline.html", "archive.html",
                     "signup.html", "lectures.html",
                     "css/main.css", "css/tokens.css"]:
            self.assertTrue((out / name).exists(), f"нет файла {name}")

    def test_no_server_paths_left(self):
        """Ссылка на / вместо файла означает битую страницу при открытии с диска."""
        import re

        out = self._export()
        for page in out.glob("*.html"):
            leftovers = re.findall(r'(?:href|src)="(/[^"]*)"', page.read_text(encoding="utf-8"))
            self.assertEqual(leftovers, [], f"{page.name}: не переписаны {leftovers}")

    def test_pages_carry_demo_banner(self):
        out = self._export()
        self.assertIn("Демонстрационная версия", (out / "index.html").read_text(encoding="utf-8"))

    def test_forms_are_disabled(self):
        out = self._export()
        html = (out / "signup.html").read_text(encoding="utf-8")
        self.assertIn("onsubmit=\"return false\"", html)
        self.assertNotIn('method="post"', html)

    def test_artifact_mode_removes_map(self):
        out = self._export(for_artifact=True)
        html = (out / "offline.html").read_text(encoding="utf-8")
        self.assertNotIn("leaflet", html.lower())
        self.assertIn("интерактивная карта", html)


class ExportMediaTest(TestCase):
    """Картинки в снимке: галерея должна работать, решения — не утекать."""

    @classmethod
    def setUpTestData(cls):
        from django.core.files.base import ContentFile
        from django.core.management import call_command

        from apps.content.models import Photo
        from apps.seasons.models import Season

        call_command("seed_demo", verbosity=0)
        Photo.objects.create(
            season=Season.objects.get(year=2026), caption="Финалисты",
            image=ContentFile(b"\x89PNG\r\n\x1a\n", name="export-test.png"),
        )

    def _export(self):
        import tempfile
        from io import StringIO
        from pathlib import Path

        from django.core.management import call_command

        out = Path(tempfile.mkdtemp()) / "dist"
        call_command("export_static", out=str(out), stdout=StringIO())
        return out

    def test_public_photos_are_carried_over(self):
        out = self._export()
        html = (out / "final.html").read_text(encoding="utf-8")
        self.assertIn('src="media/photos/', html)
        self.assertTrue(list((out / "media" / "photos").rglob("*.png")))

    def test_solutions_never_leave_the_server(self):
        """Работы участников — персональные данные, в публичный снимок нельзя."""
        out = self._export()
        self.assertFalse((out / "media" / "solutions").exists())
        for page in out.glob("*.html"):
            with self.subTest(page=page.name):
                self.assertNotIn('src="media/solutions', page.read_text(encoding="utf-8"))

    def test_nojekyll_is_written(self):
        """Без него GitHub Pages прогоняет снимок через Jekyll."""
        self.assertTrue((self._export() / ".nojekyll").exists())


class HealthzTest(TestCase):
    """По /healthz/ Docker и мониторинг решают, жив ли сайт."""

    def test_answers_ok_when_database_is_reachable(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_answers_503_when_database_is_down(self):
        from unittest.mock import patch

        with patch("apps.core.views.connection.cursor", side_effect=Exception("down")):
            self.assertEqual(self.client.get(reverse("core:healthz")).status_code, 503)


class HealthzDiskTest(TestCase):
    def test_low_disk_space_is_reported(self):
        from collections import namedtuple
        from unittest.mock import patch

        usage = namedtuple("usage", "total used free")(100, 99, 1024 ** 3)  # 1 ГБ свободно
        with patch("apps.core.views.shutil.disk_usage", return_value=usage):
            response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"low disk", response.content)


class PluralizationTest(TestCase):
    def test_plural_ru(self):
        from apps.core.plural import plural_ru

        forms = ("письмо", "письма", "писем")
        cases = {
            0: "писем",
            1: "письмо",
            2: "письма",
            3: "письма",
            4: "письма",
            5: "писем",
            6: "писем",
            10: "писем",
            11: "писем",
            12: "писем",
            14: "писем",
            19: "писем",
            20: "писем",
            21: "письмо",
            22: "письма",
            25: "писем",
            101: "письмо",
            111: "писем",
            112: "писем",
            121: "письмо",
            122: "письма",
            125: "писем",
        }
        for count, expected in cases.items():
            with self.subTest(count=count):
                self.assertEqual(plural_ru(count, *forms), expected)

    def test_get_model_plural(self):
        from apps.core.plural import get_model_plural
        from apps.mailing.models import Delivery, Newsletter
        from apps.accounts.models import User
        from apps.venues.models import Venue
        from apps.contest.models import Problem, Submission
        from apps.content.models import Lecture, News

        self.assertEqual(get_model_plural(Delivery, 1), "письмо")
        self.assertEqual(get_model_plural(Delivery, 2), "письма")
        self.assertEqual(get_model_plural(Delivery, 6), "писем")
        self.assertEqual(get_model_plural(Delivery, 21), "письмо")

        self.assertEqual(get_model_plural(Newsletter, 1), "рассылка")
        self.assertEqual(get_model_plural(Newsletter, 2), "рассылки")
        self.assertEqual(get_model_plural(Newsletter, 6), "рассылок")

        self.assertEqual(get_model_plural(User, 1), "пользователь")
        self.assertEqual(get_model_plural(User, 2), "пользователя")
        self.assertEqual(get_model_plural(User, 6), "пользователей")

        self.assertEqual(get_model_plural(Venue, 6), "площадок")
        self.assertEqual(get_model_plural(Problem, 6), "задач")
        self.assertEqual(get_model_plural(Lecture, 6), "лекций")
        self.assertEqual(get_model_plural(News, 6), "новостей")
        self.assertEqual(get_model_plural(Submission, 6), "решений")

    def test_template_tags(self):
        from django.template import Context, Template

        t1 = Template('{% load ru_plural %}{{ count|ru_plural:"письмо,письма,писем" }}')
        self.assertEqual(t1.render(Context({"count": 6})), "писем")
        self.assertEqual(t1.render(Context({"count": 1})), "письмо")
        self.assertEqual(t1.render(Context({"count": 2})), "письма")

        t2 = Template('{% load ru_plural %}{{ count|ru_plural_format:"письмо,письма,писем" }}')
        self.assertEqual(t2.render(Context({"count": 6})), "6 писем")

        from apps.mailing.models import Delivery
        t3 = Template('{% load ru_plural %}{% ru_model_plural opts count %}')
        self.assertEqual(t3.render(Context({"opts": Delivery._meta, "count": 6})), "писем")

    def test_admin_pagination_declension(self):
        from django.template import Context, Template
        from django.template.loader import render_to_string
        from apps.mailing.models import Delivery

        class DummyCL:
            def __init__(self, count):
                self.result_count = count
                self.opts = Delivery._meta
                self.formset = None
                self.pagination_required = False

        html6 = render_to_string("admin/pagination.html", {"cl": DummyCL(6), "pagination_required": False})
        self.assertIn("6 писем", html6)
        self.assertNotIn("6 письма", html6)

        html1 = render_to_string("admin/pagination.html", {"cl": DummyCL(1), "pagination_required": False})
        self.assertIn("1 письмо", html1)

        html2 = render_to_string("admin/pagination.html", {"cl": DummyCL(2), "pagination_required": False})
        self.assertIn("2 письма", html2)

        html21 = render_to_string("admin/pagination.html", {"cl": DummyCL(21), "pagination_required": False})
        self.assertIn("21 письмо", html21)

    def test_model_ngettext_patch(self):
        from django.contrib.admin.utils import model_ngettext
        from apps.mailing.models import Delivery

        self.assertEqual(model_ngettext(Delivery, 1), "письмо")
        self.assertEqual(model_ngettext(Delivery, 2), "письма")
        self.assertEqual(model_ngettext(Delivery, 6), "писем")

    def test_send_confirm_template_declensions(self):
        from django.template.loader import render_to_string
        from apps.mailing.models import Newsletter

        newsletter = Newsletter(subject="Тест")
        ctx = {
            "newsletter": newsletter,
            "count": 6,
            "sample": [],
            "preview": "Привет!",
        }
        html6 = render_to_string("admin/mailing/newsletter/send_confirm.html", ctx)
        self.assertIn("Письмо получат <strong>6</strong> человек", html6)
        self.assertIn("Да, отправить 6 писем", html6)
        self.assertNotIn("Да, отправить 6 письмам", html6)
        self.assertNotIn("6 письма", html6)

        ctx["count"] = 1
        html1 = render_to_string("admin/mailing/newsletter/send_confirm.html", ctx)
        self.assertIn("Письмо получит <strong>1</strong> человек", html1)
        self.assertIn("Да, отправить 1 письмо", html1)

        ctx["count"] = 2
        html2 = render_to_string("admin/mailing/newsletter/send_confirm.html", ctx)
        self.assertIn("Письмо получат <strong>2</strong> человека", html2)
        self.assertIn("Да, отправить 2 письма", html2)

    def test_get_model_accusative(self):
        from apps.core.plural import get_model_accusative
        from apps.mailing.models import Newsletter
        from apps.venues.models import Venue
        from apps.contest.models import Problem, Grade
        from apps.content.models import Lecture, Topic, Photo
        from apps.accounts.models import User, OrganizerProfile

        self.assertEqual(get_model_accusative(Newsletter), "рассылку")
        self.assertEqual(get_model_accusative(Venue), "площадку")
        self.assertEqual(get_model_accusative(Problem), "задачу")
        self.assertEqual(get_model_accusative(Lecture), "лекцию")
        self.assertEqual(get_model_accusative(Topic), "тему лекций")
        self.assertEqual(get_model_accusative(Photo), "фотографию")
        self.assertEqual(get_model_accusative(Grade), "оценку")
        self.assertEqual(get_model_accusative(User), "пользователя")
        self.assertEqual(get_model_accusative(OrganizerProfile), "анкету организатора")

    def test_change_list_add_button_declension(self):
        from django.template.loader import render_to_string
        from apps.mailing.models import Newsletter

        class DummyCL:
            opts = Newsletter._meta

        ctx = {
            "cl": DummyCL(),
            "has_add_permission": True,
            "is_popup": False,
            "to_field": None,
        }
        html = render_to_string("admin/change_list_object_tools.html", ctx)
        self.assertIn("Добавить рассылку", html)
        self.assertNotIn("Добавить рассылка", html)

    def test_change_form_title_declension(self):
        from django.contrib.admin import AdminSite
        from apps.mailing.admin import NewsletterAdmin
        from apps.mailing.models import Newsletter
        from django.test import RequestFactory

        from apps.accounts.models import User

        site = AdminSite()
        admin = NewsletterAdmin(Newsletter, site)
        req = RequestFactory().get("/admin/mailing/newsletter/add/")
        req.user = User(is_superuser=True, is_staff=True, role=User.Role.ADMIN)
        mock_form = type("F", (), {"is_multipart": lambda s: False})()
        mock_adminform = type("AF", (), {"form": mock_form})()
        context = {"adminform": mock_adminform, "inline_admin_formsets": []}

        # render_change_form with add=True
        resp = admin.render_change_form(req, context, add=True)
        self.assertEqual(resp.context_data["title"], "Добавить рассылку")




class AdminAjaxListEditableTests(TestCase):
    def setUp(self):
        from apps.accounts.models import User
        from apps.venues.models import Venue

        self.admin = User.objects.create_superuser("admin_ajax@test.ru", "pass12345")
        self.venue = Venue.objects.create(
            title="Тестовая площадка",
            region="Москва",
            city="Москва",
            address="Улица 1",
            latitude=55.75,
            longitude=37.61,
            status=Venue.Status.APPROVED,
            is_visible=True,
            stage_passed=False,
            registration_closed=False,
        )

    def test_changelist_template_contains_ajax_script_and_styles(self):
        self.client.force_login(self.admin)
        url = reverse("admin:venues_venue_changelist")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "admin_ajax_editable.js")
        self.assertContains(resp, "admin-ajax-indicator")
        self.assertContains(resp, 'name="form-0-registration_closed"')
        self.assertContains(resp, 'name="form-0-is_visible"')
        self.assertContains(resp, 'name="form-0-stage_passed"')

    def test_changelist_post_via_ajax_returns_json_and_updates_model(self):
        self.client.force_login(self.admin)
        url = reverse("admin:venues_venue_changelist")

        # Получаем данные formset
        get_resp = self.client.get(url)
        cl = get_resp.context["cl"]
        formset = cl.formset

        post_data = {
            "form-TOTAL_FORMS": str(len(formset.forms)),
            "form-INITIAL_FORMS": str(len(formset.forms)),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "_save": "Save",
            "form-0-id": str(self.venue.pk),
            "form-0-is_visible": "on",
            "form-0-registration_closed": "on",  # переключаем в True
        }

        resp = self.client.post(
            url,
            post_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "message": "Сохранено"})

        self.venue.refresh_from_db()
        self.assertTrue(self.venue.registration_closed)

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
                     "signup.html", "lectures.html", "consent.html",
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

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

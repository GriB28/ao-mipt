"""
Экспорт сайта в статические HTML-файлы — чтобы показать коллегам,
не поднимая сервер.

    python manage.py export_static                # -> dist/
    python manage.py export_static --for-artifact # без карты (см. ниже)

Результат: папка с готовыми страницами, перелинкованными между собой.
Открывается двойным кликом по dist/index.html, заливается на GitHub Pages
как есть. Данные — демонстрационные, из seed_demo и import_archive.

Про --for-artifact: некоторые площадки для публикации запрещают загрузку
сторонних стилей и картинок. Карта на Leaflet там не отрисуется (тайлы
OpenStreetMap не загрузятся), поэтому вместо неё подставляется список
площадок с пояснением. Для GitHub Pages флаг не нужен — карта работает.
"""

import re
import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.test import Client

# Что из media/ попадает в снимок. Всё остальное (в первую очередь
# solutions/ — работы участников) в публичную выгрузку не уходит.
PUBLIC_MEDIA = ["photos", "playlists", "lectures", "problems", "seasons"]
PUBLIC_MEDIA_RE = "|".join(PUBLIC_MEDIA)

BANNER = """
<div style="background:#19246a;color:#fff;padding:10px 16px;font-size:14px;
            text-align:center;font-family:sans-serif">
  Демонстрационная версия сайта Аэрокосмической олимпиады МФТИ.
  Данные учебные, формы не отправляются.
</div>
"""

MAP_STUB = """
<div style="border:1px solid var(--border-default);border-radius:var(--radius-md);
            padding:var(--space-5);background:var(--bg-muted)">
  <p style="margin-top:0"><strong>Здесь интерактивная карта площадок.</strong></p>
  <p class="muted">В демонстрационной версии карта не отображается: площадка,
     где опубликована эта страница, не пропускает сторонние картинки.
     На рабочем сайте здесь карта России с точками школ — по клику видно адрес,
     число свободных мест и кнопку записи.</p>
  __VENUE_LIST__
</div>
"""


class Command(BaseCommand):
    help = "Выгружает сайт в статические HTML-файлы"

    def add_arguments(self, parser):
        parser.add_argument("--out", default="dist", help="куда складывать (по умолчанию dist/)")
        parser.add_argument("--for-artifact", action="store_true",
                            help="заменить карту списком площадок")

    def handle(self, *args, **options):
        from apps.content.models import Lecture, News
        from apps.contest.models import Problem
        from apps.seasons.models import Season
        from apps.venues.models import Venue

        self.for_artifact = options["for_artifact"]
        out = Path(options["out"])
        if out.exists():
            shutil.rmtree(out)
        (out / "css").mkdir(parents=True)

        User = get_user_model()
        student = User.objects.filter(role=User.Role.PARTICIPANT).first()
        organizer = User.objects.filter(role=User.Role.ORGANIZER).first()

        # (url, имя файла, под каким пользователем рендерить)
        pages = [
            ("/", "index.html", None),
            ("/online/", "online.html", student),
            ("/offline/", "offline.html", None),
            ("/second/", "second.html", None),
            ("/final/", "final.html", None),
            ("/accounts/profile/", "profile.html", student),
            ("/offline/apply/", "apply.html", organizer),
            ("/accounts/profile/", "profile-organizer.html", organizer),
            ("/lectures/", "lectures.html", None),
            ("/lectures/archive/", "lectures-archive.html", None),
            ("/problems/", "archive.html", None),
            ("/news/", "news.html", None),
            ("/accounts/login/", "login.html", None),
            ("/accounts/password-reset/", "password-reset.html", None),
            ("/accounts/signup/", "signup.html", None),
            ("/online/my/", "my-submissions.html", student),
            ("/online/review/", "review.html", organizer),
            ("/page/about/", "about.html", None),
            ("/page/rules/", "rules.html", None),
            ("/page/consent/", "consent.html", None),
            ("/page/privacy/", "privacy.html", None),
        ]
        for problem in Problem.objects.visible():
            pages.append((f"/online/problem/{problem.pk}/", f"problem-{problem.pk}.html", student))
        from apps.contest.models import Submission

        for submission in Submission.objects.filter(is_latest=True):
            pages.append((f"/online/review/{submission.pk}/",
                          f"review-{submission.pk}.html", organizer))
        for venue in Venue.objects.public():
            pages.append((f"/offline/venue/{venue.pk}/", f"venue-{venue.pk}.html", None))
        for item in News.objects.published():
            pages.append((f"/news/{item.slug}/", f"news-{item.slug}.html", None))
        for lecture in Lecture.objects.published().select_related("season"):
            pages.append((f"/lectures/{lecture.season.slug}/{lecture.slug}/",
                          f"lecture-{lecture.slug}.html", None))
        # Текущий сезон в архив не попадает (см. content.views.problem_archive),
        # поэтому отдельной страницы по нему тоже нет.
        for season in Season.objects.published().exclude(is_active=True):
            pages.append((f"/problems/?year={season.year}", f"archive-{season.year}.html", None))

        # Карта адресов: длинные раньше коротких, иначе "/" съест всё остальное.
        self.url_map = {url: name for url, name, _ in pages}
        self.url_map["/offline/venues.geojson"] = "venues.geojson"
        # Действия, которым в статике некуда вести, возвращают на ту же
        # страницу — иначе в снимке остаётся серверный адрес.
        self.url_map["/accounts/confirm/resend/"] = "profile.html"
        self.url_map["/static/css/main.css"] = "css/main.css"
        self.url_map["/static/js/compress.js"] = "js/compress.js"

        self.venue_list_html = self._venue_list(Venue.objects.public())

        written = 0
        for url, name, user in pages:
            html = self._render(url, user)
            if html is None:
                self.stderr.write(f"  пропущено: {url}")
                continue
            (out / name).write_text(self._rewrite(html), encoding="utf-8")
            written += 1
            self.stdout.write(f"  {url:<35} -> {name}")

        for css in ("main.css", "tokens.css"):
            shutil.copy(Path(settings.BASE_DIR) / "static" / "css" / css, out / "css" / css)
        (out / "js").mkdir(exist_ok=True)
        shutil.copy(Path(settings.BASE_DIR) / "static" / "js" / "compress.js", out / "js" / "compress.js")

        # GitHub Pages по умолчанию прогоняет файлы через Jekyll, а тот
        # выбрасывает всё, что начинается с подчёркивания. Пустой файл
        # .nojekyll это отключает.
        (out / ".nojekyll").write_text("")

        copied = self._copy_media(out)
        if copied:
            self.stdout.write(f"  перенесено файлов media: {copied}")

        geojson = self._render("/offline/venues.geojson", None)
        if geojson:
            (out / "venues.geojson").write_text(geojson, encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(
            f"\nГотово: {written} страниц в {out}/. Откройте {out}/index.html"
        ))

    def _render(self, url, user):
        client = Client(SERVER_NAME="localhost")
        if user:
            client.force_login(user)
        response = client.get(url)
        if response.status_code != 200:
            return None
        return response.content.decode("utf-8")

    def _venue_list(self, venues):
        rows = "".join(
            f"<li><strong>{v.title}</strong> — {v.city}, {v.address}. "
            f"Записалось: {v.booked_count()}</li>"
            for v in venues
        )
        return f"<ul>{rows}</ul>"

    def _copy_media(self, out):
        """Переносит публичные картинки в снимок. Возвращает их число."""
        media_root = Path(settings.MEDIA_ROOT)
        copied = 0
        for folder in PUBLIC_MEDIA:
            source = media_root / folder
            if not source.is_dir():
                continue
            target = out / "media" / folder
            shutil.copytree(source, target, dirs_exist_ok=True)
            copied += sum(1 for path in target.rglob("*") if path.is_file())
        return copied

    def _rewrite(self, html):
        """Переписывает серверные адреса на имена файлов."""
        # Ссылки на архив по годам приходят как href="?year=2023"
        html = re.sub(r'href="\?year=(\d{4})"', r'href="archive-\1.html"', html)

        # Ссылки вида /accounts/login/?next=… и /online/review/1/?back=…
        # несут адрес возврата. В статике возвращаться некуда, а из-за хвоста
        # адрес не совпадает с картой ссылок и остаётся серверным — срезаем.
        html = re.sub(r'href="(/[^"?]*)\?(?:next|back)=[^"]*"', r'href="\1"', html)

        for url in sorted(self.url_map, key=len, reverse=True):
            html = html.replace(f'"{url}"', f'"{self.url_map[url]}"')
            # Якорь на странице (/online/problem/1/#my-solution) сохраняем.
            html = html.replace(f'"{url}#', f'"{self.url_map[url]}#')

        # Ссылка на админку ведёт в Django-админку, которой в снимке нет:
        # она закрыта паролем и показывается вживую. Убираем сам пункт меню.
        html = re.sub(r'<a href="/admin/"[^>]*>[^<]*</a>', "", html)

        # Публичные картинки (фотографии финалов, обложки плейлистов)
        # переезжают в снимок вместе со страницами — без них галерея
        # выглядит сломанной. Решения участников не переносим никогда:
        # это чужие работы и персональные данные.
        html = re.sub(r'(href|src)="/media/(' + PUBLIC_MEDIA_RE + r')/([^"]*)"',
                      r'\1="media/\2/\3"', html)
        html = re.sub(r'(href|src)="/media/[^"]*"', r'\1="#" data-demo-file', html)
        # Файлы решений и согласий отдаются через проверку прав — в снимок
        # они не попадают так же, как и прямые пути в /media/. Бланк согласия
        # тоже: он собирается из персональных данных.
        html = re.sub(r'href="/(?:online/file|accounts/consent)/[^"]*"', 'href="#" data-demo-file', html)

        # Формы никуда не ведут — пусть не создают ложных ожиданий.
        html = re.sub(r'<form([^>]*)method="post"', r'<form\1onsubmit="return false" data-demo', html)

        if self.for_artifact:
            html = self._replace_map(html)

        return html.replace("<body>", "<body>" + BANNER, 1)

    def _replace_map(self, html):
        """Убирает Leaflet: карту заменяем списком, скрипты и стили вырезаем."""
        if 'id="map"' not in html:
            return html
        stub = MAP_STUB.replace("__VENUE_LIST__", self.venue_list_html)
        html = re.sub(r'<div id="map".*?</div>', stub, html, flags=re.DOTALL)
        html = re.sub(r'<link[^>]*leaflet[^>]*>', "", html)
        html = re.sub(r'<script[^>]*leaflet[^>]*></script>', "", html)
        # Инлайновый скрипт инициализации карты без самой карты только сломает страницу.
        html = re.sub(r'<script>\s*const el = document\.getElementById\(.map.\).*?</script>',
                      "", html, flags=re.DOTALL)
        return html

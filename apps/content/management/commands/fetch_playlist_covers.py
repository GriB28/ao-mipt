"""
Скачивает превью для плейлистов с YouTube.

    python manage.py fetch_playlist_covers

Картинка берётся у YouTube один раз и хранится у нас: так плейлисты
выглядят одинаково и не зависят от доступности чужого сервера.

Для ВКонтакте превью автоматически не достать — загрузите картинку
вручную в админке (Контент → Плейлисты → превью) или оставьте пустым,
тогда покажется иконка платформы.
"""

import urllib.request

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.content.models import Playlist

# Разрешения превью по убыванию: берём первое, которое отдаётся.
THUMBNAIL_SIZES = ["maxresdefault", "sddefault", "hqdefault"]


class Command(BaseCommand):
    help = "Скачивает обложки плейлистов с YouTube"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="перекачать даже те, у которых превью уже есть")

    def handle(self, *args, **options):
        saved = skipped = failed = 0

        for playlist in Playlist.objects.all():
            if playlist.cover and not options["force"]:
                skipped += 1
                continue

            video_id = playlist.video_id
            if not video_id:
                self.stdout.write(f"  {playlist.title}: превью не достать ({playlist.platform_title})")
                skipped += 1
                continue

            content = self._download(video_id)
            if content is None:
                self.stderr.write(f"  {playlist.title}: не удалось скачать превью")
                failed += 1
                continue

            playlist.cover.save(f"{video_id}.jpg", ContentFile(content), save=True)
            self.stdout.write(f"  {playlist.title}: превью сохранено")
            saved += 1

        self.stdout.write(self.style.SUCCESS(
            f"Сохранено: {saved}, пропущено: {skipped}, ошибок: {failed}"
        ))

    def _download(self, video_id):
        for size in THUMBNAIL_SIZES:
            url = f"https://img.youtube.com/vi/{video_id}/{size}.jpg"
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read()
            except Exception:
                continue
            # YouTube отдаёт заглушку 120×90 весом около килобайта,
            # когда картинки такого размера нет.
            if len(data) > 5000:
                return data
        return None

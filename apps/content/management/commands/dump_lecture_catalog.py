"""
Пересобирает apps/content/lecture_catalog.py из того, что сейчас в базе.

    python manage.py import_lectures info_videos.xlsx   # загрузить таблицу
    python manage.py dump_lecture_catalog               # зафиксировать в коде

Зачем: таблица организаторов в репозиторий не кладётся, а лекции у всех,
кто склонировал проект, должны быть. Каталог — обычный питоновский файл,
его видно в диффе и можно поправить руками.
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.content.lecture_catalog import SEASON_PLAYLISTS
from apps.content.models import Lecture, Topic

TARGET = Path("apps/content/lecture_catalog.py")

HEADER = '''"""
Каталог лекций прошлых сезонов.

Данные пришли из таблицы организаторов (info_videos.xlsx) командой
import_lectures и зафиксированы здесь, чтобы у всех, кто склонировал
репозиторий, лекции были сразу — сама таблица в git не кладётся.

Обновлять так: положить свежую таблицу рядом, прогнать
    python manage.py import_lectures info_videos.xlsx
и пересобрать этот файл командой
    python manage.py dump_lecture_catalog
"""

'''


class Command(BaseCommand):
    help = "Выгружает темы и лекции из базы в lecture_catalog.py"

    def handle(self, *args, **options):
        lines = [HEADER, "# Темы: код, название, раздел, порядок.", "TOPICS = ["]
        for topic in Topic.objects.order_by("section", "order"):
            lines.append(f"    ({topic.slug!r}, {topic.title!r}, "
                         f"{topic.section!r}, {topic.order}),")
        lines += ["]", "", "# Плейлисты сезонов целиком.", "SEASON_PLAYLISTS = ["]
        for year, url in SEASON_PLAYLISTS:
            lines.append(f"    ({year}, {url!r}),")
        lines += ["]", "", "# Лекции: год сезона, тема, название, лектор, ссылка, описание.",
                  "LECTURES = ["]

        lectures = (Lecture.objects.exclude(topic__isnull=True)
                    .select_related("season", "topic")
                    .order_by("season__year", "pk"))
        for lecture in lectures:
            lines.append(
                f"    ({lecture.season.year}, {lecture.topic.slug!r}, {lecture.title!r}, "
                f"{lecture.lecturer!r}, {lecture.video_url!r}, {lecture.description!r}),"
            )
        lines += ["]", ""]

        TARGET.write_text("\n".join(lines), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"{TARGET}: тем {Topic.objects.count()}, лекций {lectures.count()}"
        ))

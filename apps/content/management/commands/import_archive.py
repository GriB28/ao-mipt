"""
Импорт архива прошлых лет с публичной папки Яндекс.Диска.

Сначала посмотрите, что получится, не трогая базу:

    python manage.py import_archive --dry-run

Затем импортируйте. По умолчанию файлы скачиваются к нам на сервер,
кроме тех, что больше 50 МБ — на них остаётся прямая ссылка на Яндекс.Диск:

    python manage.py import_archive

Если файлы качать не нужно, только ссылки:

    python manage.py import_archive --no-download

Команда идемпотентна: материал опознаётся по пути в исходном архиве,
повторный запуск ничего не задвоит.

--- О нумерации папок ---

Названия папок на диске — это КАЛЕНДАРНЫЙ ГОД ТУРА, а один сезон олимпиады
охватывает два года: отбор осенью, финал весной. Поэтому:

    Отбор2023 + Закл2024  =  один сезон, АО IV
    Отбор2025 + Закл2026  =  один сезон, АО VI

Если импортировать «в лоб» по номеру папки, архив развалится на половинки
сезонов. Здесь это учтено: сезон именуется по году финала.
"""

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.content.models import ArchiveMaterial
from apps.seasons.models import Season, Stage

API = "https://cloud-api.yandex.net/v1/disk/public/resources"
DEFAULT_PUBLIC_KEY = "https://disk.yandex.ru/d/2-JgAsDO28MMfQ"

# Римская цифра сезона: АО I прошла в сезоне, завершившемся в 2021 году.
FIRST_SEASON_YEAR = 2020
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]

FOLDER_RE = re.compile(r"^(Отбор|Закл)\s*(\d{4})$", re.IGNORECASE)

DATA_EXTENSIONS = {".csv", ".txt", ".xlsx", ".zip", ".stl", ".fts", ".fits", ".wav", ".dat"}
CODE_EXTENSIONS = {".py", ".ipynb", ".cpp", ".c", ".java"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif"}


def roman(year: int) -> str:
    index = year - FIRST_SEASON_YEAR - 1
    return ROMAN[index] if 0 <= index < len(ROMAN) else str(year)


def classify(name: str) -> str:
    """Определяет тип материала по имени файла."""
    lower = name.lower()
    ext = Path(name).suffix.lower()

    # Расширение важнее имени: файл sol1.txt на 44 МБ — это данные,
    # а не разбор, хотя в названии и есть «sol».
    if ext in VIDEO_EXTENSIONS:
        return ArchiveMaterial.Kind.VIDEO
    if ext in CODE_EXTENSIONS:
        return ArchiveMaterial.Kind.CODE
    if ext in DATA_EXTENSIONS or ext in IMAGE_EXTENSIONS:
        return ArchiveMaterial.Kind.DATA

    # Дальше остались документы — их различаем по названию.
    if any(w in lower for w in ("результат", "results")):
        return ArchiveMaterial.Kind.RESULTS
    if any(w in lower for w in ("sol", "решени", "разбор", "критери", "answer")):
        return ArchiveMaterial.Kind.SOLUTIONS
    if any(w in lower for w in ("task", "problem", "задани", "задач", "qualify", "zadaniy")):
        return ArchiveMaterial.Kind.PROBLEMS
    if ext in (".pdf", ".djvu", ".doc", ".docx"):
        # Документ без узнаваемого имени — вероятнее всего условия.
        return ArchiveMaterial.Kind.PROBLEMS
    return ArchiveMaterial.Kind.OTHER


def problem_number(path: str):
    """Достаёт номер задачи из пути вида «/Закл2023/3 задача/spec.png»."""
    match = re.search(r"/(\d+)\s*задач", path, re.IGNORECASE)
    return int(match.group(1)) if match else None


class Command(BaseCommand):
    help = "Импортирует архив олимпиады с публичной папки Яндекс.Диска"

    def add_arguments(self, parser):
        parser.add_argument("--public-key", default=DEFAULT_PUBLIC_KEY,
                            help="ссылка на публичную папку Яндекс.Диска")
        parser.add_argument("--dry-run", action="store_true",
                            help="только показать план, ничего не менять")
        parser.add_argument("--no-download", action="store_true",
                            help="не скачивать файлы, оставить только ссылки на Яндекс.Диск")
        parser.add_argument("--max-size", type=int, default=50,
                            help="не скачивать файлы больше N МБ (по умолчанию 50)")

    def handle(self, *args, **options):
        self.public_key = options["public_key"]
        self.dry_run = options["dry_run"]
        self.download = not options["no_download"]
        self.max_bytes = options["max_size"] * 1024 * 1024

        self.created = self.updated = self.skipped = self.downloaded = 0

        root = self._fetch("/")
        folders = [i for i in root["_embedded"]["items"] if i["type"] == "dir"]

        if not folders:
            self.stderr.write("В папке нет подпапок — нечего импортировать.")
            return

        for folder in sorted(folders, key=lambda f: f["name"]):
            self._import_folder(folder)

        loose = [i for i in root["_embedded"]["items"] if i["type"] == "file"]
        if loose:
            self.stdout.write(self.style.WARNING(
                f"\nВ корне лежат {len(loose)} файлов вне папок сезонов — "
                "они пропущены, разложите их или заведите вручную:"
            ))
            for item in loose:
                self.stdout.write(f"    {item['name']}")

        summary = (f"\nСоздано: {self.created}, обновлено: {self.updated}, "
                   f"пропущено: {self.skipped}")
        if self.download:
            summary += f", скачано файлов: {self.downloaded}"
        if self.dry_run:
            summary = "\nЭто был пробный запуск, база не изменялась." + summary
        self.stdout.write(self.style.SUCCESS(summary))

    # --- работа с API ----------------------------------------------------

    def _fetch(self, path, offset=0):
        query = urllib.parse.urlencode({
            "public_key": self.public_key, "path": path, "limit": 200, "offset": offset,
        })
        with urllib.request.urlopen(f"{API}?{query}", timeout=60) as response:
            return json.load(response)

    def _walk(self, path="/"):
        """Рекурсивно возвращает все файлы внутри папки."""
        offset = 0
        while True:
            data = self._fetch(path, offset)
            embedded = data.get("_embedded", {})
            items = embedded.get("items", [])
            for item in items:
                if item["type"] == "dir":
                    yield from self._walk(item["path"])
                else:
                    yield item
            offset += len(items)
            if not items or offset >= embedded.get("total", 0):
                break

    # --- импорт ----------------------------------------------------------

    def _import_folder(self, folder):
        match = FOLDER_RE.match(folder["name"].strip())
        if not match:
            self.stdout.write(self.style.WARNING(
                f"Папка «{folder['name']}» не похожа на тур — пропущена."
            ))
            return

        tour, year = match.group(1).lower(), int(match.group(2))
        is_qualifying = tour == "отбор"
        # Отбор идёт осенью года N, финал — весной N+1. Сезон зовём по году финала.
        season_year = year + 1 if is_qualifying else year

        season = self._get_season(season_year)
        stage = self._get_stage(season, is_qualifying) if season else None

        self.stdout.write(
            f"\n{folder['name']} → сезон {season_year} "
            f"(АО {roman(season_year)}), этап: {'отбор' if is_qualifying else 'финал'}"
        )

        for item in self._walk(folder["path"]):
            self._import_file(item, season, stage, folder["path"])

    def _get_season(self, year):
        title = f"Аэрокосмическая олимпиада МФТИ {roman(year)}"
        if self.dry_run:
            return Season.objects.filter(year=year).first()
        season, created = Season.objects.get_or_create(
            year=year,
            defaults={"slug": f"ao{str(year)[-2:]}", "title": title,
                      "subtitle": f"Сезон {year - 1}/{str(year)[-2:]}", "is_published": True},
        )
        if created:
            self.stdout.write(f"    создан сезон: {title}")
        return season

    def _get_stage(self, season, is_qualifying):
        from django.utils import timezone

        slug = "otbor" if is_qualifying else "final"
        title = "Отборочный этап" if is_qualifying else "Финал"
        if self.dry_run:
            return season.stages.filter(slug=slug).first() if season else None

        tz = timezone.get_current_timezone()
        # Точные даты прошлых сезонов неизвестны, но важен порядок:
        # отбор осенью, финал весной. Иначе финал встанет в архиве
        # раньше отбора, к которому он относится.
        if is_qualifying:
            start = timezone.datetime(season.year - 1, 11, 1, tzinfo=tz)
            end = timezone.datetime(season.year, 1, 31, tzinfo=tz)
            order = 1
        else:
            start = timezone.datetime(season.year, 4, 1, tzinfo=tz)
            end = timezone.datetime(season.year, 4, 30, tzinfo=tz)
            order = 3

        stage, created = Stage.objects.get_or_create(
            season=season, slug=slug,
            defaults={
                "kind": Stage.Kind.ONLINE if is_qualifying else Stage.Kind.OFFLINE,
                "title": title, "starts_at": start, "ends_at": end,
                "order": order, "is_published": True,
            },
        )
        if not created and (stage.order, stage.title) != (order, title):
            # Приводим к актуальному виду этапы, заведённые прошлыми
            # версиями команды: порядок, название и сроки.
            stage.order = order
            stage.title = title
            stage.starts_at = start
            stage.ends_at = end
            stage.save(update_fields=["order", "title", "starts_at", "ends_at", "updated_at"])
        return stage

    def _import_file(self, item, season, stage, folder_path):
        name = item["name"]
        path = item["path"]
        size = item.get("size") or 0
        kind = classify(name)
        number = problem_number(path)

        # Подпапка внутри тура попадает в описание: «helper/asteroid»
        subfolder = path[len(folder_path):].strip("/").rsplit("/", 1)[0]

        label = f"    {name} [{kind}]"
        if number:
            label += f" задача {number}"
        if size > self.max_bytes:
            label += f" — {size / 1024 / 1024:.0f} МБ, ссылкой"
        self.stdout.write(label)

        if self.dry_run or season is None:
            self.skipped += 1
            return

        material, created = ArchiveMaterial.objects.get_or_create(
            season=season, source_path=path,
            defaults={
                "stage": stage,
                "kind": kind,
                "title": Path(name).stem.replace("_", " "),
                "problem_number": number,
                "description": subfolder,
                "size_bytes": size,
                # Ссылка ведёт на конкретный файл, а не на всю папку:
                # Яндекс.Диск понимает <публичная ссылка>/<путь внутри папки>.
                "external_url": self._file_url(path),
                "order": number or 100,
            },
        )
        if created:
            self.created += 1
        else:
            self.updated += 1

        if self.download and not material.file and 0 < size <= self.max_bytes:
            self._download_file(material, path, name)

    def _file_url(self, path):
        """Прямая ссылка на файл внутри публичной папки Яндекс.Диска."""
        return self.public_key.rstrip("/") + urllib.parse.quote(path)

    def _download_file(self, material, path, name):
        query = urllib.parse.urlencode({"public_key": self.public_key, "path": path})
        try:
            with urllib.request.urlopen(f"{API}/download?{query}", timeout=60) as response:
                href = json.load(response)["href"]
            with urllib.request.urlopen(href, timeout=300) as response:
                content = response.read()
        except Exception as exc:
            self.stderr.write(f"      не скачалось: {exc}")
            return
        material.file.save(name, ContentFile(content), save=True)
        self.downloaded += 1

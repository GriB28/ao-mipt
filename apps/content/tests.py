"""Импорт архива: главное — не перепутать сезоны и типы файлов."""

from django.test import TestCase
from django.utils import timezone

from apps.content.management.commands.import_archive import (
    FOLDER_RE,
    classify,
    problem_number,
    roman,
)
from apps.content.models import ArchiveMaterial


class SeasonMappingTest(TestCase):
    """Папка на диске названа по календарному году тура, а сезон идёт через два года."""

    def _season_year(self, folder):
        match = FOLDER_RE.match(folder)
        tour, year = match.group(1).lower(), int(match.group(2))
        return year + 1 if tour == "отбор" else year

    def test_qualifying_round_belongs_to_next_years_season(self):
        # Отбор2023 и Закл2024 — один сезон, АО IV
        self.assertEqual(self._season_year("Отбор2023"), 2024)
        self.assertEqual(self._season_year("Закл2024"), 2024)

    def test_latest_season_pair(self):
        self.assertEqual(self._season_year("Отбор2025"), 2026)
        self.assertEqual(self._season_year("Закл2026"), 2026)

    def test_roman_numerals_match_known_seasons(self):
        # Известно из файлов архива: aoIV.pdf лежит в Отбор2023 → сезон 2024
        self.assertEqual(roman(2024), "IV")
        self.assertEqual(roman(2026), "VI")
        self.assertEqual(roman(2027), "VII")

    def test_unknown_folder_is_not_matched(self):
        self.assertIsNone(FOLDER_RE.match("helper"))
        self.assertIsNone(FOLDER_RE.match("Разное2020"))


class ClassifyTest(TestCase):
    def test_solutions_detected_by_name(self):
        for name in ["AO25FINAL_SOL.pdf", "решения_AO_V_сезон.pdf",
                     "Отборочный этап АО VI - Решения и критерии.pdf"]:
            self.assertEqual(classify(name), ArchiveMaterial.Kind.SOLUTIONS, name)

    def test_problems_detected_by_name(self):
        for name in ["АО24_ЗАДАНИЯ_ТЕОР.pdf", "aomipt2023_qualify.pdf", "ZADANIYa.pdf"]:
            self.assertEqual(classify(name), ArchiveMaterial.Kind.PROBLEMS, name)

    def test_unnamed_pdf_treated_as_problems(self):
        self.assertEqual(classify("aoIV.pdf"), ArchiveMaterial.Kind.PROBLEMS)

    def test_extension_wins_over_name(self):
        """sol1.txt на 44 МБ — это данные, а не разбор."""
        self.assertEqual(classify("sol1.txt"), ArchiveMaterial.Kind.DATA)

    def test_code_and_data_and_video(self):
        self.assertEqual(classify("read_stl.py"), ArchiveMaterial.Kind.CODE)
        self.assertEqual(classify("Ballon.ipynb"), ArchiveMaterial.Kind.CODE)
        self.assertEqual(classify("atmosphere.csv"), ArchiveMaterial.Kind.DATA)
        self.assertEqual(classify("0.fts"), ArchiveMaterial.Kind.DATA)
        self.assertEqual(classify("Разбор.mp4"), ArchiveMaterial.Kind.VIDEO)

    def test_results_detected(self):
        self.assertEqual(classify("Результаты_отборочного_этапа_АО_VI.pdf"),
                         ArchiveMaterial.Kind.RESULTS)


class ProblemNumberTest(TestCase):
    def test_number_extracted_from_folder(self):
        self.assertEqual(problem_number("/Закл2023/3 задача/spec.png"), 3)
        self.assertEqual(problem_number("/Закл2023/1 задача/gantel.pdf"), 1)

    def test_no_number_outside_problem_folders(self):
        self.assertIsNone(problem_number("/Закл2024/АО24_ЗАДАНИЯ_ТЕОР.pdf"))


class ArchiveMaterialTest(TestCase):
    def test_url_prefers_own_file_then_external(self):
        from apps.seasons.models import Season

        season = Season.objects.create(year=2099, slug="s", title="S", is_published=True)
        material = ArchiveMaterial.objects.create(
            season=season, title="Условия", external_url="https://disk.yandex.ru/d/x",
        )
        self.assertEqual(material.url, "https://disk.yandex.ru/d/x")

    def test_size_display(self):
        from apps.seasons.models import Season

        season = Season.objects.create(year=2098, slug="s2", title="S2", is_published=True)
        big = ArchiveMaterial.objects.create(season=season, title="Видео",
                                             size_bytes=1584 * 1024 * 1024)
        small = ArchiveMaterial.objects.create(season=season, title="Данные", size_bytes=26 * 1024)
        self.assertEqual(big.size_display, "1584 МБ")
        self.assertEqual(small.size_display, "26 КБ")


class PlaylistTest(TestCase):
    """Плейлисты лекций: площадка определяется по ссылке автоматически."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_platform_detected_from_url(self):
        from apps.content.models import Playlist

        vk = Playlist.objects.filter(url__contains="vkvideo.ru").first()
        yt = Playlist.objects.filter(url__contains="youtube.com").first()
        self.assertEqual(vk.platform, "vk")
        self.assertEqual(vk.platform_title, "ВКонтакте")
        self.assertEqual(yt.platform, "youtube")

    def test_playlists_live_in_the_archive(self):
        """Плейлисты — это записи прошлых лет, им место в архиве лекций."""
        html = self.client.get("/lectures/archive/").content.decode()
        self.assertIn("playlist-card", html)
        self.assertIn("platform-vk", html)
        self.assertIn("platform-youtube", html)

    def test_current_season_page_shows_lectures_not_playlists(self):
        """На основной странице — лекции этого сезона, без плейлистов прошлых лет.

        Лекций сезона ещё нет, и страница честно говорит об этом, а не
        подсовывает записи прошлых лет.
        """
        html = self.client.get("/lectures/").content.decode()
        self.assertNotIn("playlist-card", html)
        self.assertIn("ещё не начались", html)

    def test_unpublished_playlist_hidden(self):
        from apps.content.models import Playlist

        Playlist.objects.all().update(is_published=False)
        html = self.client.get("/lectures/archive/").content.decode()
        self.assertNotIn("playlist-card", html)


class LectureEmbedTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_playlist_link_shows_button_not_broken_player(self):
        """Из ссылки на плейлист плеер не собирается — показываем кнопку."""
        from apps.content.models import Lecture

        lecture = Lecture.objects.first()
        lecture.video_url = "https://vkvideo.ru/playlist/-17906_48144875"
        lecture.save()
        html = self.client.get(lecture.get_absolute_url()).content.decode()
        self.assertNotIn("<iframe", html)
        self.assertIn("Смотреть в ВКонтакте", html)

    def test_vk_lecture_plays_on_the_page(self):
        """Записи во ВКонтакте должны проигрываться прямо на сайте."""
        from apps.content.models import Lecture

        lecture = Lecture.objects.filter(video_url__contains="vkvideo.ru/video").first()
        html = self.client.get(lecture.get_absolute_url()).content.decode()
        self.assertIn("vk.com/video_ext.php", html)

    def test_youtube_lecture_embeds_player(self):
        from apps.content.models import Lecture

        lecture = Lecture.objects.first()
        lecture.video_url = "https://www.youtube.com/watch?v=Z5rYrIb1ER0"
        lecture.save()
        html = self.client.get(lecture.get_absolute_url()).content.decode()
        self.assertIn("<iframe", html)
        self.assertIn("youtube-nocookie.com/embed", html)

    def test_vk_lecture_embeds_vk_player(self):
        from apps.content.models import Lecture

        lecture = Lecture.objects.first()
        lecture.video_url = "https://vkvideo.ru/video-17906_456239123"
        lecture.save()
        html = self.client.get(lecture.get_absolute_url()).content.decode()
        self.assertIn("vk.com/video_ext.php", html)


class ArchiveOrderTest(TestCase):
    """Отборочный этап должен стоять перед финалом, к которому относится."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def _stage_titles(self, year):
        import re

        html = self.client.get(f"/problems/?year={year}").content.decode()
        return re.findall(r"<h3>(.*?)</h3>", html)

    def test_archive_lists_both_tours(self):
        from apps.seasons.models import Season, Stage

        season = Season.objects.create(year=2098, slug="a98", title="A", is_published=True)
        base = __import__("django.utils.timezone", fromlist=["timezone"]).now()
        from datetime import timedelta

        for slug, title, order, offset in [
            ("final", "Финал", 3, 150), ("otbor", "Отборочный этап", 1, 10),
        ]:
            stage = Stage.objects.create(
                season=season, slug=slug, title=title, order=order,
                kind=Stage.Kind.ONLINE, starts_at=base + timedelta(days=offset),
                ends_at=base + timedelta(days=offset + 5), is_published=True,
            )
            ArchiveMaterial.objects.create(
                season=season, stage=stage, title=f"Разбор {title}",
                kind=ArchiveMaterial.Kind.SOLUTIONS,
            )

        self.assertEqual(self._stage_titles(2098), ["Отборочный этап", "Финал"])

    def test_empty_season_not_offered_in_archive(self):
        """Текущий сезон без материалов в архиве не нужен — он на главной."""
        html = self.client.get("/problems/").content.decode()
        self.assertNotIn("Материалы этого сезона пока не выложены", html)


class ArchiveOrderingTest(TestCase):
    """Архив: что показывается сверху и какие сезоны вообще в списке."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_current_season_is_not_in_the_archive(self):
        """Задачи текущего сезона живут в разделе тура, а не в архиве."""
        response = self.client.get("/problems/")
        years = [s.year for s in response.context["seasons"]]
        self.assertNotIn(2027, years)

    def test_problems_come_before_extra_files(self):
        """Заходят за условиями и разборами, а не за csv с данными."""
        from apps.content.models import ArchiveMaterial
        from apps.seasons.models import Season, Stage

        season = Season.objects.get(year=2026)
        stage = Stage.objects.create(
            season=season, kind=Stage.Kind.ONLINE, slug="t", title="Тур",
            starts_at=timezone.now(), ends_at=timezone.now(), is_published=True,
        )
        for kind in (ArchiveMaterial.Kind.DATA, ArchiveMaterial.Kind.PROBLEMS,
                     ArchiveMaterial.Kind.SOLUTIONS):
            ArchiveMaterial.objects.create(
                season=season, stage=stage, kind=kind, title=f"файл {kind}",
                external_url="https://example.ru/f",
            )

        response = self.client.get("/problems/?year=2026")
        blocks = dict(response.context["materials_by_stage"])["Тур"]
        self.assertEqual(
            [title for title, _ in blocks],
            ["Условия задач", "Решения и разборы", "Данные к задачам"],
        )

    def test_file_name_shows_its_extension(self):
        """Без расширения непонятно, откроется это в браузере или скачается."""
        from apps.content.models import ArchiveMaterial
        from apps.seasons.models import Season

        material = ArchiveMaterial(
            season=Season.objects.get(year=2026),
            title="Разбор отборочного этапа",
            source_path="/Закл2026/Разбор отборочного этапа.pdf",
        )
        self.assertEqual(material.extension, "pdf")
        self.assertEqual(material.display_name, "Разбор отборочного этапа.pdf")

    def test_extension_not_doubled_if_title_already_has_it(self):
        from apps.content.models import ArchiveMaterial
        from apps.seasons.models import Season

        material = ArchiveMaterial(
            season=Season.objects.get(year=2026),
            title="signal.txt", source_path="/Отбор2025/signal.txt",
        )
        self.assertEqual(material.display_name, "signal.txt")


class LectureApprovalTest(TestCase):
    """Лекцию добавляет организатор, показывает участникам администратор."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def setUp(self):
        from apps.accounts.models import User
        from apps.seasons.models import Season

        self.organizer = User.objects.create_user("lec@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER)
        self.other = User.objects.create_user("lec2@e.ru", "olymp12345",
                                              role=User.Role.ORGANIZER)
        self.kid = User.objects.create_user("kid6@e.ru", "olymp12345")
        self.season = Season.objects.active()

    def _create(self, **extra):
        from django.urls import reverse

        self.client.force_login(self.organizer)
        data = {
            "season": self.season.pk,
            "title": "Ракетные двигатели",
            "video_url": "https://vkvideo.ru/video-17906_456239245",
        }
        return self.client.post(reverse("content:lecture_new"), data | extra)

    def test_new_lecture_is_invisible_until_approved(self):
        from apps.content.models import Lecture

        self._create(submit_for_review="1")
        lecture = Lecture.objects.get(title="Ракетные двигатели")
        self.assertEqual(lecture.status, Lecture.Status.PENDING)
        self.assertNotIn(lecture, Lecture.objects.published())
        self.assertNotIn("Ракетные двигатели", self.client.get("/lectures/").content.decode())

    def test_approved_lecture_appears_for_everyone(self):
        from apps.content.models import Lecture

        self._create(submit_for_review="1")
        Lecture.objects.filter(title="Ракетные двигатели").update(status=Lecture.Status.APPROVED)

        self.client.force_login(self.kid)
        self.assertIn("Ракетные двигатели", self.client.get("/lectures/").content.decode())

    def test_participant_cannot_add_lectures(self):
        from django.urls import reverse

        self.client.force_login(self.kid)
        self.assertEqual(self.client.get(reverse("content:lecture_new")).status_code, 403)

    def test_playlist_link_is_refused_with_an_explanation(self):
        """Из плейлиста плеер не собирается — ловим это на форме, а не на странице."""
        from apps.content.models import Lecture

        response = self._create(video_url="https://vkvideo.ru/playlist/-17906_48144875")
        self.assertIn("ссылка на плейлист", response.content.decode())
        self.assertFalse(Lecture.objects.filter(title="Ракетные двигатели").exists())

    def test_unknown_platform_is_refused(self):
        from apps.content.models import Lecture

        self._create(video_url="https://example.com/video/1")
        self.assertFalse(Lecture.objects.filter(title="Ракетные двигатели").exists())

    def test_address_is_made_from_the_title(self):
        from apps.content.models import Lecture

        self._create()
        self.assertTrue(Lecture.objects.get(title="Ракетные двигатели").slug)

    def test_organizer_sees_only_own_lectures(self):
        from django.urls import reverse

        self._create()
        self.client.force_login(self.other)
        html = self.client.get(reverse("content:lecture_manage")).content.decode()
        self.assertNotIn("Ракетные двигатели", html)

    def test_editing_a_rejected_lecture_returns_it_to_drafts(self):
        from django.urls import reverse

        from apps.content.models import Lecture

        self._create()
        lecture = Lecture.objects.get(title="Ракетные двигатели")
        Lecture.objects.filter(pk=lecture.pk).update(status=Lecture.Status.REJECTED)

        self.client.force_login(self.organizer)
        self.client.post(reverse("content:lecture_edit", args=[lecture.pk]), {
            "season": self.season.pk, "title": "Ракетные двигатели",
            "video_url": "https://vkvideo.ru/video-17906_456239245",
        })
        lecture.refresh_from_db()
        self.assertEqual(lecture.status, Lecture.Status.DRAFT)


class FinalPhotosTest(TestCase):
    """Галерея финалов на странице финала."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_photos_are_shown_with_their_year(self):
        from django.core.files.base import ContentFile

        from apps.content.models import Photo
        from apps.seasons.models import Season

        season = Season.objects.get(year=2026)
        Photo.objects.create(
            season=season, caption="Финалисты",
            image=ContentFile(b"\x89PNG\r\n\x1a\n", name="test-final.png"),
        )
        html = self.client.get("/final/").content.decode()
        self.assertIn("АО VI", html)
        self.assertIn("Финалисты", html)

    def test_unpublished_photo_is_hidden(self):
        from django.core.files.base import ContentFile

        from apps.content.models import Photo

        Photo.objects.create(
            caption="Черновик", is_published=False,
            image=ContentFile(b"\x89PNG\r\n\x1a\n", name="draft.png"),
        )
        self.assertNotIn("Черновик", self.client.get("/final/").content.decode())

    def test_empty_gallery_says_so_instead_of_breaking(self):
        html = self.client.get("/final/").content.decode()
        self.assertIn("Финалы прошлых лет", html)

    def test_gallery_runs_from_the_first_season_to_the_last(self):
        """Галерея читается как история олимпиады, а не как лента новостей."""
        from django.core.files.base import ContentFile

        from apps.content.models import Photo
        from apps.seasons.models import Season

        for year in (2023, 2021, 2022):
            Photo.objects.create(
                season=Season.objects.get_or_create(
                    year=year, defaults={"slug": f"s{year}", "title": f"АО {year}",
                                         "is_published": True})[0],
                image=ContentFile(b"\x89PNG\r\n\x1a\n", name=f"y{year}.png"),
            )
        years = [p.season.year for p in Photo.objects.published()]
        self.assertEqual(years, sorted(years))


class LectureCatalogTest(TestCase):
    """Каталог лекций: разделы, темы и разбор названий."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_catalog_is_loaded(self):
        from apps.content.models import Lecture, Topic

        self.assertGreater(Lecture.objects.count(), 50)
        self.assertGreater(Topic.objects.count(), 10)

    def test_every_lecture_has_a_topic(self):
        """Лекция без темы проваливается в «Прочее» и теряется."""
        from apps.content.models import Lecture

        self.assertEqual(Lecture.objects.filter(topic__isnull=True).count(), 0)

    def test_sections_come_in_the_declared_order(self):
        """Физика, программирование, общее — а не по алфавиту кодов."""
        html = self.client.get("/lectures/archive/").content.decode()
        positions = [html.index(name) for name in ("Физика", "Программирование", "Общее")]
        self.assertEqual(positions, sorted(positions))

    def test_topics_group_the_lectures(self):
        html = self.client.get("/lectures/archive/").content.decode()
        for topic in ("Основы Python", "Небесная механика и баллистика", "Оптика и излучение"):
            with self.subTest(topic=topic):
                self.assertIn(topic, html)

    def test_section_filter_narrows_the_list(self):
        response = self.client.get("/lectures/archive/?section=programming")
        titles = [name for name, _, _ in response.context["sections"]]
        self.assertEqual(titles, ["Программирование"])

    def test_season_filter_narrows_the_list(self):
        response = self.client.get("/lectures/archive/?season=ao22")
        self.assertTrue(response.context["lectures"])
        for lecture in response.context["lectures"]:
            with self.subTest(lecture=lecture.title):
                self.assertEqual(lecture.season.slug, "ao22")
        # Сезоны в фильтре подписаны учебными годами, и выбор одного
        # сезона не убирает остальные из списка.
        html = response.content.decode()
        self.assertIn("2021/2022", html)
        self.assertGreater(len(response.context["season_choices"]), 1)

    def test_there_is_no_topic_filter(self):
        html = self.client.get("/lectures/archive/").content.decode()
        self.assertNotIn('name="topic"', html)

    def test_seed_is_idempotent(self):
        """Повторный запуск seed_demo не задваивает лекции."""
        from django.core.management import call_command

        from apps.content.models import Lecture

        before = Lecture.objects.count()
        call_command("seed_demo", verbosity=0)
        self.assertEqual(Lecture.objects.count(), before)


class TopicMatchingTest(TestCase):
    """Разбор названий по темам: правила проверяются сверху вниз."""

    def test_python_lecture_about_odes_goes_to_numerical(self):
        """Частное правило должно побеждать общее «python»."""
        from apps.content.management.commands.import_lectures import match_topic

        self.assertEqual(match_topic("Знакомство с Python. Решение ОДУ"), "numerical")
        self.assertEqual(match_topic("Знакомство с Python. Функции"), "python")

    def test_mixed_lecture_goes_to_its_main_subject(self):
        from apps.content.management.commands.import_lectures import match_topic

        self.assertEqual(
            match_topic("Вращательное движение. Закон Гука. Тепловое расширение"),
            "mechanics",
        )

    def test_problem_reviews_are_separated(self):
        from apps.content.management.commands.import_lectures import match_topic

        self.assertEqual(match_topic("Разбор заданий теор. тура"), "solutions")

    def test_unknown_title_is_left_without_a_topic(self):
        """Лучше показать «без темы», чем засунуть лекцию не туда."""
        from apps.content.management.commands.import_lectures import match_topic

        self.assertIsNone(match_topic("Что-то совершенно новое"))

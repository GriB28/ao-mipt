"""Схема этапов: формат прохождения определяет, что видно на главной."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.seasons.models import Season, Stage


class StageFormatTest(TestCase):
    def setUp(self):
        self.season = Season.objects.create(year=2099, slug="s", title="S",
                                            is_active=True, is_published=True)
        self.now = timezone.now()

    def _stage(self, kind, slug="st", **extra):
        return Stage.objects.create(
            season=self.season, kind=kind, slug=slug, title="Этап",
            starts_at=self.now - timedelta(days=1),
            ends_at=self.now + timedelta(days=1),
            is_published=True, **extra,
        )

    def test_hybrid_stage_offers_both_ways(self):
        """Первый отбор: дистанционно или на площадке — оба варианта равноценны."""
        stage = self._stage(Stage.Kind.HYBRID)
        self.assertTrue(stage.has_online)
        self.assertTrue(stage.has_offline)

    def test_online_stage_is_not_offline(self):
        stage = self._stage(Stage.Kind.ONLINE)
        self.assertTrue(stage.has_online)
        self.assertFalse(stage.has_offline)

    def test_offline_stage_is_not_online(self):
        stage = self._stage(Stage.Kind.OFFLINE)
        self.assertFalse(stage.has_online)
        self.assertTrue(stage.has_offline)

    def test_proctoring_flag(self):
        stage = self._stage(Stage.Kind.ONLINE, requires_proctoring=True)
        self.assertTrue(stage.requires_proctoring)

    def test_stages_ordered_by_order_field(self):
        """Порядок на схеме задаётся полем, а не датами: даты уточняются позже."""
        third = self._stage(Stage.Kind.OFFLINE, slug="c", order=3)
        first = self._stage(Stage.Kind.HYBRID, slug="a", order=1)
        second = self._stage(Stage.Kind.ONLINE, slug="b", order=2)
        self.assertEqual(list(self.season.stages.all()), [first, second, third])


class HomeSchemeTest(TestCase):
    """Схема на главной: четыре кликабельные карточки и вложенные группы."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_all_four_stages_are_shown(self):
        html = self.client.get("/").content.decode()
        for title in ("Очный этап", "Дистанционный этап", "Второй тур", "Финал"):
            with self.subTest(stage=title):
                self.assertIn(title, html)

    def test_each_card_is_a_link_to_its_page(self):
        """Карточка — ссылка целиком: работают Tab и «открыть в новой вкладке»."""
        html = self.client.get("/").content.decode()
        for url in ("/offline/", "/online/", "/second/", "/final/"):
            with self.subTest(url=url):
                self.assertIn(f'<a class="stage-card" href="{url}"', html)

    def test_nested_groups_are_present(self):
        """Три вложенные области — на них держится вся читаемость схемы."""
        html = self.client.get("/").content.decode()
        for css_class in ("scheme-all", "scheme-qualifying", "scheme-primary"):
            with self.subTest(css_class=css_class):
                self.assertIn(css_class, html)

    def test_first_level_says_both_formats_are_allowed(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Можно участвовать в одном или обоих этапах", html)

    def test_dates_come_from_the_database(self):
        """Даты не зашиты в вёрстку — иначе разойдутся с расписанием."""
        from apps.seasons.models import Stage

        Stage.objects.filter(slug="ochny").update(short_note="1–2 марта")
        self.assertIn("1–2 марта", self.client.get("/").content.decode())

    def test_final_shows_where_it_happens(self):
        self.assertIn("Кампус МФТИ", self.client.get("/").content.decode())

    def test_practice_stage_is_not_on_the_scheme(self):
        """Песочница открыта всегда — этапом олимпиады она не является."""
        self.assertNotIn("Тренировочная задача", self.client.get("/").content.decode())

    def test_no_progress_indicators(self):
        """По ТЗ схема спокойная: ни текущего этапа, ни номеров, ни таймеров."""
        html = self.client.get("/").content.decode()
        for noise in ("идёт сейчас", "Этап 1", "прогресс"):
            with self.subTest(noise=noise):
                self.assertNotIn(noise, html)

    def test_unpublished_stage_drops_off_the_scheme(self):
        from apps.seasons.models import Stage

        Stage.objects.filter(slug="final").update(is_published=False)
        # Смотрим только внутрь схемы: ссылка на финал есть ещё и в
        # верхнем меню, и её снимать не нужно.
        html = self.client.get("/").content.decode()
        scheme = html.split('class="scheme"')[1].split("</section>")[0]
        self.assertNotIn('href="/final/"', scheme)
        self.assertIn('href="/offline/"', scheme)


class ScheduleTest(TestCase):
    """Даты сезона: полночь на старте, последняя секунда суток на финише."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def _stage(self, slug):
        from apps.seasons.models import Stage

        return Stage.objects.get(season__year=2027, slug=slug)

    def test_every_stage_starts_at_midnight_and_ends_at_2359(self):
        from django.utils import timezone

        from apps.seasons.models import Stage

        for stage in Stage.objects.filter(season__year=2027):
            with self.subTest(stage=stage.slug):
                starts = timezone.localtime(stage.starts_at)
                ends = timezone.localtime(stage.ends_at)
                self.assertEqual((starts.hour, starts.minute, starts.second), (0, 0, 0))
                self.assertEqual((ends.hour, ends.minute, ends.second), (23, 59, 59))

    def test_announced_dates(self):
        from django.utils import timezone

        expected = {
            "ochny": ((2026, 10, 19), (2026, 10, 24)),
            "otbor-1": ((2026, 11, 15), (2027, 1, 15)),
            "otbor-2": ((2027, 2, 14), (2027, 2, 28)),
            "final": ((2027, 4, 8), (2027, 4, 12)),
        }
        for slug, (start, end) in expected.items():
            with self.subTest(stage=slug):
                stage = self._stage(slug)
                self.assertEqual(timezone.localtime(stage.starts_at).timetuple()[:3], start)
                self.assertEqual(timezone.localtime(stage.ends_at).timetuple()[:3], end)

    def test_two_formats_of_the_same_first_round(self):
        """Очный тур и дистанционный отбор равноценны: это один этап в двух
        форматах, писать нужно что-то одно. Поэтому порядок у них общий."""
        self.assertEqual(self._stage("ochny").order, self._stage("otbor-1").order)

    def test_second_round_comes_after_both_formats(self):
        self.assertGreater(self._stage("otbor-2").order, self._stage("ochny").order)
        self.assertGreater(self._stage("otbor-2").order, self._stage("otbor-1").order)

    def test_offline_format_is_earlier_in_the_calendar(self):
        """При равном порядке этапы сортируются по дате: очный тур в октябре."""
        self.assertLess(self._stage("ochny").starts_at, self._stage("otbor-1").starts_at)

    def test_second_round_points_to_the_proctoring_platform(self):
        """Тур идёт не у нас, а на exams.mipt.ru — ссылка должна быть видна."""
        self.assertEqual(self._stage("otbor-2").platform_url, "https://exams.mipt.ru")

    def test_venue_booking_is_open_for_the_offline_round(self):
        """Иначе кнопка «записаться» есть, а записаться нельзя."""
        from django.utils import timezone

        stage = self._stage("ochny")
        self.assertLessEqual(timezone.localtime(stage.registration_opens_at).date(),
                             timezone.localdate())


class PracticeStageTest(TestCase):
    """Песочница: проверить отправку решения можно в любой день."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_practice_stage_is_open_right_now(self):
        from apps.seasons.models import Stage

        self.assertTrue(Stage.objects.get(season__year=2027, is_practice=True).is_open)

    def test_practice_problem_offered_on_the_contest_page(self):
        from apps.accounts.models import User

        self.client.force_login(User.objects.get(email="student@example.ru"))
        html = self.client.get("/online/").content.decode()
        self.assertIn("Тренировочная задача", html)

    def test_practice_stage_is_not_the_current_round(self):
        """Иначе песочница подменит собой настоящий тур на странице задач."""
        response = self.client.get("/online/")
        self.assertEqual(response.context["stage"].slug, "otbor-1")

    def test_practice_problem_accepts_submissions_out_of_season(self):
        from apps.contest.models import Problem

        problem = Problem.objects.get(stage__is_practice=True)
        self.assertTrue(problem.accepts_submissions)


class HomeStatusTest(TestCase):
    """Строка состояния под баннером: что с олимпиадой прямо сейчас."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def _shift(self, slug, starts_days, ends_days):
        from datetime import timedelta

        from django.utils import timezone

        from apps.seasons.models import Stage

        now = timezone.now()
        Stage.objects.filter(slug=slug).update(
            starts_at=now + timedelta(days=starts_days),
            ends_at=now + timedelta(days=ends_days),
        )

    def test_running_stage_is_announced_with_its_deadline(self):
        self._shift("ochny", -1, 3)
        html = self.client.get("/").content.decode()
        self.assertIn("Сейчас идёт", html)
        self.assertIn("очный этап", html)

    def test_upcoming_stage_is_announced_with_its_start(self):
        html = self.client.get("/").content.decode()
        self.assertIn("начнётся", html)
        self.assertIn("Очный этап", html)

    def test_running_stage_wins_over_upcoming(self):
        """Если один тур идёт, а другой впереди, человеку нужен идущий."""
        self._shift("otbor-1", -1, 5)
        html = self.client.get("/").content.decode()
        self.assertIn("Сейчас идёт", html)
        self.assertNotIn("начнётся", html)

    def test_practice_sandbox_is_never_the_status(self):
        """Песочница открыта всегда — она не этап олимпиады."""
        html = self.client.get("/").content.decode()
        self.assertNotIn("Тренировочная задача", html)

    def test_finished_season_says_nothing_rather_than_lying(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.seasons.models import Stage

        past = timezone.now() - timedelta(days=30)
        Stage.objects.update(starts_at=past, ends_at=past)
        html = self.client.get("/").content.decode()
        self.assertNotIn("Сейчас идёт", html)
        self.assertNotIn("начнётся", html)


class HomeSectionsTest(TestCase):
    """На главной остались только схема и новости."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("seed_demo", verbosity=0)

    def test_section_cards_are_gone(self):
        html = self.client.get("/").content.decode()
        main = html.split("<main")[1].split("</main>")[0]
        for gone in ("Условия текущего этапа", "Карта школ", "Подготовительный курс"):
            with self.subTest(block=gone):
                self.assertNotIn(gone, main)

    def test_news_stayed(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Новости", html)
        self.assertIn("Открыта регистрация", html)

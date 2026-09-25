"""Дедлайны — самое дорогое место: ошибка здесь ломает олимпиаду."""

import tempfile
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.testing import make_eligible
from apps.contest.models import Grade, Problem, Submission, SubmissionFile
from apps.seasons.models import Season, Stage


def open_problem(max_score=Decimal(10), author=None):
    """Задача этапа, который идёт прямо сейчас.

    Демо-данные задач дистанционного тура не содержат (их заводят
    организаторы), поэтому тесты, которым нужна открытая задача,
    заводят её сами.
    """
    now = timezone.now()
    season = Season.objects.get(year=2027)
    stage, _ = Stage.objects.get_or_create(
        season=season, slug="open-now",
        defaults={"kind": Stage.Kind.ONLINE, "title": "Идущий этап", "order": 50,
                  "starts_at": now - timedelta(days=1), "ends_at": now + timedelta(days=1),
                  "is_published": True},
    )
    number = stage.problems.count() + 1
    return Problem.objects.create(stage=stage, number=number, title=f"Задача {number}",
                                  max_score=max_score, created_by=author,
                                  status=Problem.Status.APPROVED)


class DeadlineTest(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.season = Season.objects.create(year=2099, slug="s", title="S", is_active=True, is_published=True)
        self.user = User.objects.create_user("a@b.ru", "pass12345")

    def _problem(self, starts, ends):
        # Счётчик в slug: у этапа он уникален в пределах сезона, а один
        # тест заводит несколько этапов с одинаковыми датами.
        self._stage_no = getattr(self, "_stage_no", 0) + 1
        stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.ONLINE, slug=f"st{self._stage_no}",
            title="Этап", starts_at=starts, ends_at=ends, is_published=True,
        )
        return Problem.objects.create(stage=stage, number=1, title="Задача",
                                      max_score=Decimal(10), status=Problem.Status.APPROVED)

    def test_open_stage_accepts_submissions(self):
        p = self._problem(self.now - timedelta(days=1), self.now + timedelta(days=1))
        self.assertTrue(p.accepts_submissions)
        self.assertFalse(Submission.objects.create(user=self.user, problem=p).is_late)

    def test_closed_stage_rejects_submissions(self):
        p = self._problem(self.now - timedelta(days=2), self.now - timedelta(days=1))
        self.assertFalse(p.accepts_submissions)

    def test_submission_after_deadline_is_marked_late(self):
        p = self._problem(self.now - timedelta(days=2), self.now - timedelta(minutes=1))
        self.assertTrue(Submission.objects.create(user=self.user, problem=p).is_late)

    def test_new_submission_replaces_previous_as_latest(self):
        p = self._problem(self.now - timedelta(days=1), self.now + timedelta(days=1))
        first = Submission.objects.create(user=self.user, problem=p)
        second = Submission.objects.create(user=self.user, problem=p)
        first.refresh_from_db()
        self.assertFalse(first.is_latest)
        self.assertTrue(second.is_latest)

    def test_unapproved_problem_hidden(self):
        """Пока администратор не одобрил задачу, участники её не видят."""
        for status in (Problem.Status.DRAFT, Problem.Status.PENDING, Problem.Status.REJECTED):
            with self.subTest(status=status):
                p = self._problem(self.now - timedelta(days=1), self.now + timedelta(days=1))
                p.status = status
                p.save()
                self.assertNotIn(p, Problem.objects.visible())
                p.delete()

    def test_problem_hidden_until_stage_starts(self):
        """Время публикации общее для этапа — его начало."""
        p = self._problem(self.now + timedelta(hours=1), self.now + timedelta(days=1))
        self.assertNotIn(p, Problem.objects.visible())


class ReviewAccessTest(TestCase):
    """Проверять решения может организатор — прямо на сайте, без админки."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.participant = User.objects.create_user("kid2@e.ru", "olymp12345")
        self.organizer = User.objects.create_user("org2@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER)

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("contest:review_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_participant_is_refused(self):
        self.client.force_login(self.participant)
        self.assertEqual(self.client.get(reverse("contest:review_list")).status_code, 403)

    def test_organizer_gets_in(self):
        self.client.force_login(self.organizer)
        self.assertEqual(self.client.get(reverse("contest:review_list")).status_code, 200)

    def test_tours_offer_their_own_tools_only(self):
        """Задачи живут на дистанционном туре, площадки — на очном.

        Смешивать их в одной панели незачем: это разные туры и разная
        работа, а лишние ссылки только мешают искать нужную.
        """
        self.client.force_login(self.organizer)

        online = self.client.get("/online/").content.decode()
        self.assertIn(reverse("contest:review_list"), online)
        self.assertIn(reverse("contest:problem_new"), online)
        self.assertNotIn(reverse("venues:apply"), online)

        offline = self.client.get("/offline/").content.decode()
        self.assertIn(reverse("venues:apply"), offline)
        self.assertNotIn(reverse("contest:problem_new"), offline)

    def test_participant_sees_no_organizer_panel(self):
        self.client.force_login(self.participant)
        html = self.client.get("/online/").content.decode()
        self.assertNotIn("organizer-bar", html)


class ReviewGradingTest(TestCase):
    """Оценка выставляется на той же странице, где видно файлы решения."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.organizer = User.objects.create_user("org3@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER)
        self.kid = User.objects.create_user("kid3@e.ru", "olymp12345")
        # Задача с заданным максимумом: именно на ней проверяется верхняя
        # граница балла. У задач без максимума её нет — это отдельный тест.
        self.problem = open_problem()
        # Проверять можно только свои задачи: назначаем организатора
        # дополнительным проверяющим, как это сделал бы администратор.
        self.problem.reviewers.add(self.organizer)
        self.submission = Submission.objects.create(user=self.kid, problem=self.problem)
        self.client.force_login(self.organizer)

    def _grade(self, **extra):
        data = {"score": "7", "comment": "Не хватает оценки погрешности.",
                "status": Grade.Status.GRADED}
        return self.client.post(reverse("contest:review_detail", args=[self.submission.pk]),
                                data | extra)

    def test_grade_is_saved_with_its_reviewer(self):
        self._grade()
        grade = Grade.objects.get(submission=self.submission)
        self.assertEqual(grade.score, Decimal("7"))
        self.assertEqual(grade.reviewer, self.organizer)
        self.assertEqual(grade.status, Grade.Status.GRADED)

    def test_score_above_maximum_is_rejected(self):
        """Иначе опечатка «100» вместо «10» молча портит итоговую таблицу."""
        response = self._grade(score="1000")
        self.assertFormError(response.context["form"], "score",
                             f"Больше максимума за задачу ({self.problem.max_score:g}).")
        self.assertFalse(Grade.objects.filter(submission=self.submission).exists())

    def test_problem_without_a_maximum_accepts_any_score(self):
        """Максимум необязателен: шкалу можно уточнить уже при проверке."""
        free = open_problem(max_score=None)
        free.reviewers.add(self.organizer)
        submission = Submission.objects.create(user=self.kid, problem=free)

        self.client.post(reverse("contest:review_detail", args=[submission.pk]),
                         {"score": "42", "comment": "", "status": Grade.Status.GRADED})
        self.assertEqual(Grade.objects.get(submission=submission).score, Decimal("42"))

    def test_negative_score_is_rejected(self):
        self._grade(score="-5")
        self.assertFalse(Grade.objects.filter(submission=self.submission).exists())

    def test_regrading_updates_instead_of_duplicating(self):
        self._grade()
        self._grade(score="9")
        self.assertEqual(Grade.objects.filter(submission=self.submission).count(), 1)
        self.assertEqual(Grade.objects.get(submission=self.submission).score, Decimal("9"))

    def test_queue_hides_checked_work_by_default(self):
        """Заходят сюда за непроверенным — оценённое не должно мешаться."""
        queue = f"{reverse('contest:review_list')}?problem={self.problem.pk}"
        link = reverse("contest:review_detail", args=[self.submission.pk])

        self.assertIn(link, self.client.get(queue).content.decode())

        self._grade()
        self.assertNotIn(link, self.client.get(queue).content.decode())
        # Но найти его можно, переключив фильтр.
        self.assertIn(link, self.client.get(f"{queue}&status=graded").content.decode())

    def test_score_is_hidden_until_results_are_published(self):
        """Пока ведомость заполняется, баллы участникам показывать нельзя."""
        self._grade()
        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:my_submissions")).content.decode()
        self.assertIn("скоро", html)

    def test_participant_sees_the_score_after_publication(self):
        self._grade()
        stage = self.problem.stage
        stage.results_published = True
        stage.save(update_fields=["results_published"])

        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:my_submissions")).content.decode()
        self.assertNotIn("скоро", html)
        self.assertIn("7", html)


class ProblemApprovalTest(TestCase):
    """Задачу заводит организатор, показывает участникам — администратор."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        from apps.seasons.models import Stage

        self.organizer = User.objects.create_user("author@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER)
        self.other = User.objects.create_user("other@e.ru", "olymp12345",
                                              role=User.Role.ORGANIZER)
        self.kid = User.objects.create_user("kid9@e.ru", "olymp12345")
        self.stage = Stage.objects.get(season__year=2027, slug="otbor-1")

    def _create(self, **extra):
        self.client.force_login(self.organizer)
        data = {"stage": self.stage.pk, "number": 90, "title": "Новая задача",
                "statement_html": "Найдите $v_0$."}
        return self.client.post(reverse("contest:problem_new"), data | extra)

    def test_new_problem_is_invisible_to_participants(self):
        self._create(submit_for_review="1")
        problem = Problem.objects.get(number=90)
        self.assertEqual(problem.status, Problem.Status.PENDING)
        self.assertNotIn(problem, Problem.objects.visible())

    def test_draft_and_review_are_different_buttons(self):
        self._create(save_draft="1")
        self.assertEqual(Problem.objects.get(number=90).status, Problem.Status.DRAFT)

    def test_author_is_remembered(self):
        self._create()
        self.assertEqual(Problem.objects.get(number=90).created_by, self.organizer)

    def test_statement_is_required(self):
        response = self._create(statement_html="")
        self.assertIn("Нужно условие", response.content.decode())
        self.assertFalse(Problem.objects.filter(number=90).exists())

    def test_participant_cannot_add_problems(self):
        self.client.force_login(self.kid)
        self.assertEqual(self.client.get(reverse("contest:problem_new")).status_code, 403)

    def test_approved_problem_waits_for_the_stage_to_start(self):
        """Одобрить можно заранее, но участники увидят задачу только с начала этапа."""
        self._create(submit_for_review="1")
        problem = Problem.objects.get(number=90)
        problem.status = Problem.Status.APPROVED
        problem.save()
        self.stage.starts_at = timezone.now() + timedelta(days=30)
        self.stage.save()
        self.assertNotIn(problem, Problem.objects.visible())

        self.stage.starts_at = timezone.now() - timedelta(minutes=1)
        self.stage.save()
        self.assertIn(problem, Problem.objects.visible())

    def test_admin_approves_on_the_site(self):
        """Администратор одобряет и правит задачу без Django-админки."""
        self._create(submit_for_review="1")
        problem = Problem.objects.get(number=90)
        admin = User.objects.get(email="admin@example.ru")
        self.client.force_login(admin)
        page = self.client.get(reverse("contest:problem_edit", args=[problem.pk])).content.decode()
        self.assertIn("Сохранить и одобрить", page)

        data = {"stage": self.stage.pk, "number": 90, "title": "Новая задача (исправлено)",
                "statement_html": "Найдите $v_0$.", "approve": "1"}
        self.client.post(reverse("contest:problem_edit", args=[problem.pk]), data)
        problem.refresh_from_db()
        self.assertEqual(problem.status, Problem.Status.APPROVED)
        self.assertEqual(problem.title, "Новая задача (исправлено)")

    def test_admin_returns_problem_with_a_comment(self):
        self._create(submit_for_review="1")
        problem = Problem.objects.get(number=90)
        self.client.force_login(User.objects.get(email="admin@example.ru"))
        data = {"stage": self.stage.pk, "number": 90, "title": "Новая задача",
                "statement_html": "Найдите $v_0$.", "reject": "1"}
        url = reverse("contest:problem_edit", args=[problem.pk])

        self.client.post(url, data)  # без комментария — не принимается
        problem.refresh_from_db()
        self.assertEqual(problem.status, Problem.Status.PENDING)

        self.client.post(url, data | {"moderation_comment": "Уточните условие."})
        problem.refresh_from_db()
        self.assertEqual(problem.status, Problem.Status.REJECTED)
        self.assertEqual(problem.moderation_comment, "Уточните условие.")

    def test_organizer_cannot_approve(self):
        self._create(submit_for_review="1")
        problem = Problem.objects.get(number=90)
        self.client.force_login(self.organizer)
        data = {"stage": self.stage.pk, "number": 90, "title": "Новая задача",
                "statement_html": "Найдите $v_0$.", "approve": "1"}
        self.client.post(reverse("contest:problem_edit", args=[problem.pk]), data)
        problem.refresh_from_db()
        self.assertNotEqual(problem.status, Problem.Status.APPROVED)

    def test_online_tour_announces_start_date_before_it_begins(self):
        self.stage.starts_at = timezone.now() + timedelta(days=30)
        self.stage.save()
        html = self.client.get(reverse("contest:problem_list")).content.decode()
        self.assertIn("Этап начнётся", html)
        self.assertNotIn("Приём решений закрыт", html)

    def test_organizer_sees_only_own_problems(self):
        self._create()
        self.client.force_login(self.other)
        html = self.client.get(reverse("contest:problem_manage")).content.decode()
        self.assertNotIn("Новая задача", html)

    def test_assigned_reviewer_sees_the_problem(self):
        """Администратор может назначить проверяющим кого-то кроме автора."""
        self._create()
        problem = Problem.objects.get(number=90)
        problem.reviewers.add(self.other)

        self.client.force_login(self.other)
        html = self.client.get(reverse("contest:problem_manage")).content.decode()
        self.assertIn("Новая задача", html)

    def test_stranger_cannot_review_someone_elses_problem(self):
        self._create()
        problem = Problem.objects.get(number=90)
        submission = Submission.objects.create(user=self.kid, problem=problem)

        self.client.force_login(self.other)
        response = self.client.get(reverse("contest:review_detail", args=[submission.pk]))
        self.assertEqual(response.status_code, 403)

    def test_editing_a_rejected_problem_returns_it_to_drafts(self):
        self._create()
        problem = Problem.objects.get(number=90)
        problem.status = Problem.Status.REJECTED
        problem.save()

        self.client.force_login(self.organizer)
        self.client.post(reverse("contest:problem_edit", args=[problem.pk]),
                         {"stage": self.stage.pk, "number": 90, "title": "Новая задача",
                          "statement_html": "Исправил."})
        problem.refresh_from_db()
        self.assertEqual(problem.status, Problem.Status.DRAFT)


class ManagerViewTest(TestCase):
    """Организатор и админ управляют, а не участвуют: вид сайта у них другой."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.organizer = User.objects.get(email="organizer@example.ru")
        self.kid = User.objects.get(email="student@example.ru")
        self.problem = open_problem(author=self.organizer)

    def test_manager_gets_tools_instead_of_the_upload_form(self):
        self.client.force_login(self.organizer)
        html = self.client.get(reverse("contest:problem_detail", args=[self.problem.pk])).content.decode()
        self.assertNotIn("Сдать решение", html)
        self.assertIn("Редактировать задачу", html)

    def test_participant_still_gets_the_upload_form(self):
        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:problem_detail", args=[self.problem.pk])).content.decode()
        self.assertIn("Сдать решение", html)
        self.assertNotIn("Редактировать задачу", html)

    def test_manager_is_not_offered_the_practice_problem(self):
        self.client.force_login(self.organizer)
        html = self.client.get("/online/").content.decode()
        self.assertNotIn("Проверить, что всё работает", html)

    def test_max_score_is_not_shown_to_anyone(self):
        """Максимум за задачу участникам не показывается."""
        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:problem_detail", args=[self.problem.pk])).content.decode()
        self.assertNotIn("максимум", html.lower())

    def test_formulas_and_figure_survive_to_the_page(self):
        self.problem.statement_html = "Скорость $v_0 = \\sqrt{2gh}$."
        self.problem.save()
        self.client.force_login(self.kid)  # задачи — только вошедшим
        html = self.client.get(reverse("contest:problem_detail", args=[self.problem.pk])).content.decode()
        # Формулы разбирает KaTeX в браузере — на сервере важно лишь,
        # что исходный текст дошёл целым и блок помечен классом math.
        self.assertIn("\\sqrt{2gh}", html)
        self.assertIn('class="card prose math"', html)


class ScoringTest(TestCase):
    """Итоги считаются в одном месте: задачи не равнозначны."""

    def test_unchecked_problem_is_not_a_zero(self):
        """«Не проверено» и «ноль баллов» — разные вещи."""
        from apps.contest.scoring import total

        problem = Problem(number=1, title="З")
        self.assertEqual(total([(problem, None), (problem, Decimal("5"))]), Decimal("5"))

    def test_empty_ledger_gives_zero_not_an_error(self):
        from apps.contest.scoring import total

        self.assertEqual(total([]), Decimal(0))

    def test_weights_are_applied_through_one_place(self):
        """Когда веса появятся, они должны подействовать везде сразу."""
        from unittest.mock import patch

        from apps.contest import scoring

        problem = Problem(number=1, title="З")
        with patch.object(scoring, "problem_weight", return_value=Decimal(2)):
            self.assertEqual(scoring.total([(problem, Decimal("5"))]), Decimal("10"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="olymp-test-media-"))
class LastSubmissionTest(TestCase):
    """Участник видит, что именно он отправил, и может открыть свой файл."""

    def setUp(self):
        now = timezone.now()
        season = Season.objects.create(year=2098, slug="ls", title="S", is_active=True, is_published=True)
        self.stage = Stage.objects.create(
            season=season, kind=Stage.Kind.ONLINE, slug="on", title="Этап",
            starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1), is_published=True,
        )
        self.problem = Problem.objects.create(stage=self.stage, number=1, title="Орбита",
                                              status=Problem.Status.APPROVED)
        self.kid = make_eligible(User.objects.create_user("kid@e.ru", "olymp12345"))
        self.client.force_login(self.kid)

    def _send(self, name="reshenie.pdf", answer=""):
        f = SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")
        return self.client.post(reverse("contest:submit", args=[self.problem.pk]),
                                {"files": [f], "answer": answer, "comment": ""})

    def _page(self):
        return self.client.get(reverse("contest:problem_detail", args=[self.problem.pk])).content.decode()

    def test_nothing_is_shown_before_the_first_attempt(self):
        self.assertNotIn("Ваше последнее решение", self._page())

    def test_last_attempt_is_shown_with_its_file(self):
        response = self._send(answer="42 км/с")
        self.assertRedirects(response, reverse("contest:problem_detail", args=[self.problem.pk]) + "#my-solution")
        html = self._page()
        self.assertIn("Ваше последнее решение", html)
        self.assertIn("reshenie.pdf", html)
        self.assertIn("42 км/с", html)
        self.assertIn("ждёт проверки", html)

    def test_older_attempts_go_to_history(self):
        self._send("pervoe.pdf")
        self._send("vtoroe.pdf")
        html = self._page()
        self.assertIn("Предыдущие версии (1)", html)
        # Последняя версия — в карточке, первая — ниже, в истории.
        self.assertLess(html.index("vtoroe.pdf"), html.index("pervoe.pdf"))

    def test_score_is_hidden_until_results_are_published(self):
        self._send()
        sub = Submission.objects.get(user=self.kid)
        Grade.objects.create(submission=sub, score=Decimal(7), comment="Нет рисунка орбиты",
                             status=Grade.Status.GRADED)
        html = self._page()
        self.assertNotIn("Нет рисунка орбиты", html)
        self.assertIn("Балл появится", html)

        self.stage.results_published = True
        self.stage.save()
        html = self._page()
        self.assertIn("Нет рисунка орбиты", html)

    def test_owner_can_open_the_file(self):
        self._send()
        sf = SubmissionFile.objects.get()
        response = self.client.get(sf.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", self.client.get(sf.get_absolute_url() + "?download=1")["Content-Disposition"])

    def test_other_participant_cannot_open_the_file(self):
        self._send()
        sf = SubmissionFile.objects.get()
        self.client.force_login(User.objects.create_user("other@e.ru", "olymp12345"))
        self.assertEqual(self.client.get(sf.get_absolute_url()).status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        self._send()
        sf = SubmissionFile.objects.get()
        self.client.logout()
        self.assertEqual(self.client.get(sf.get_absolute_url()).status_code, 302)

    def test_reviewer_of_the_problem_can_open_the_file(self):
        self._send()
        sf = SubmissionFile.objects.get()
        organizer = User.objects.create_user("org@e.ru", "olymp12345", role=User.Role.ORGANIZER)
        self.client.force_login(organizer)
        self.assertEqual(self.client.get(sf.get_absolute_url()).status_code, 404)
        self.problem.reviewers.add(organizer)
        self.assertEqual(self.client.get(sf.get_absolute_url()).status_code, 200)

    @override_settings(PROTECTED_MEDIA_ACCEL_PREFIX="/protected-media/")
    def test_behind_nginx_the_file_is_handed_over_by_accel_redirect(self):
        self._send("решение.pdf")
        sf = SubmissionFile.objects.get()
        response = self.client.get(sf.get_absolute_url())
        self.assertTrue(response["X-Accel-Redirect"].startswith("/protected-media/solutions/"))
        self.assertEqual(response.content, b"")

    def test_list_shows_when_the_problem_was_submitted(self):
        self._send()
        html = self.client.get(reverse("contest:problem_list")).content.decode()
        self.assertIn("#my-solution", html)


class SecurityTest(TestCase):
    """Найденные при аудите дыры — чтобы не вернулись."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.organizer = User.objects.get(email="organizer@example.ru")
        self.kid = User.objects.get(email="student@example.ru")

    def test_script_in_statement_is_removed(self):
        """Скрипт в условии не выполняется ни у участника, ни у администратора."""
        problem = open_problem(author=self.organizer)
        problem.statement_html = ('<p onclick="steal()">Найдите $v$.</p><script>steal()</script>'
                                  '<img src="x" onerror="steal()"><a href="javascript:steal()">x</a>')
        problem.save()
        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:problem_detail", args=[problem.pk])).content.decode()
        self.assertIn("Найдите $v$.", html)
        for bad in ("<script>steal", "onclick=", "onerror=", "javascript:steal"):
            self.assertNotIn(bad, html)

    def test_statement_is_cleaned_when_saved(self):
        stage = Stage.objects.get(season__year=2027, slug="otbor-1")
        self.client.force_login(self.organizer)
        self.client.post(reverse("contest:problem_new"), {
            "stage": stage.pk, "number": 77, "title": "З",
            "statement_html": "<p>Условие</p><script>alert(1)</script>"})
        self.assertEqual(Problem.objects.get(number=77).statement_html, "<p>Условие</p>")

    def test_back_link_cannot_lead_off_site(self):
        problem = open_problem(author=self.organizer)
        submission = Submission.objects.create(user=self.kid, problem=problem)
        self.client.force_login(self.organizer)
        url = reverse("contest:review_detail", args=[submission.pk])
        queue = reverse("contest:review_list")
        for bad in ("javascript:alert(1)", "https://evil.example/", "//evil.example/"):
            with self.subTest(back=bad):
                page = self.client.get(url, {"back": bad})
                self.assertEqual(page.context["back"], queue)
                saved = self.client.post(url, {"score": "1", "comment": "", "status": "graded",
                                               "back": bad})
                self.assertEqual(saved["Location"], queue)
        # Своя очередь с фильтрами по-прежнему работает.
        good = f"{queue}?problem={problem.pk}&status=todo"
        self.assertEqual(self.client.get(url, {"back": good}).context["back"], good)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="olymp-test-media-"),
                       MAX_ATTEMPTS_PER_PROBLEM=2)
    def test_attempts_per_problem_are_limited(self):
        problem = open_problem()
        self.client.force_login(self.kid)
        for _ in range(3):
            f = SimpleUploadedFile("r.pdf", b"%PDF", content_type="application/pdf")
            self.client.post(reverse("contest:submit", args=[problem.pk]), {"files": [f]})
        self.assertEqual(Submission.objects.filter(user=self.kid, problem=problem).count(), 2)

    def test_organizer_cannot_submit_solutions(self):
        problem = open_problem()
        self.client.force_login(self.organizer)
        f = SimpleUploadedFile("r.pdf", b"%PDF", content_type="application/pdf")
        response = self.client.post(reverse("contest:submit", args=[problem.pk]), {"files": [f]})
        self.assertEqual(response.status_code, 403)

    def test_attachment_upload_path_works(self):
        """Материалы к задаче из админки раньше падали с ошибкой 500."""
        from apps.contest.models import ProblemAttachment, problem_upload_path

        problem = open_problem()
        path = problem_upload_path(ProblemAttachment(problem=problem), "data.csv")
        self.assertTrue(path.endswith("/data.csv"))
        # Имя файла задачи не угадать: в пути случайная папка.
        self.assertNotEqual(problem_upload_path(problem, "a.png"), problem_upload_path(problem, "a.png"))

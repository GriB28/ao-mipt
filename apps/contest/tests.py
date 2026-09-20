"""Дедлайны — самое дорогое место: ошибка здесь ломает олимпиаду."""

from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.contest.models import Grade, Problem, Submission
from apps.seasons.models import Season, Stage


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

    def test_problem_hidden_until_publish_at(self):
        p = self._problem(self.now - timedelta(days=1), self.now + timedelta(days=1))
        p.publish_at = self.now + timedelta(hours=1)
        p.save()
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
        self.problem = (Problem.objects.visible()
                        .filter(stage__is_practice=False, max_score__isnull=False).first())
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
        free = Problem.objects.visible().filter(max_score__isnull=True).first()
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

    def test_statement_is_required_in_some_form(self):
        response = self._create(statement_html="")
        self.assertIn("Нужно условие", response.content.decode())
        self.assertFalse(Problem.objects.filter(number=90).exists())

    def test_participant_cannot_add_problems(self):
        self.client.force_login(self.kid)
        self.assertEqual(self.client.get(reverse("contest:problem_new")).status_code, 403)

    def test_approved_problem_becomes_visible(self):
        self._create(submit_for_review="1")
        problem = Problem.objects.get(number=90)
        problem.status = Problem.Status.APPROVED
        problem.save()
        self.assertIn(problem, Problem.objects.visible())

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
        self.problem = Problem.objects.visible().filter(stage__is_practice=False).first()

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

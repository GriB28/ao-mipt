"""Рассылки: главное — не отправить письмо дважды и не промахнуться аудиторией."""

from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import ParticipantProfile, User
from apps.contest.models import Problem, Submission
from apps.mailing.models import Delivery, Newsletter
from apps.mailing.services import queue_newsletter, render_body, send_pending
from apps.participation.models import Registration
from apps.seasons.models import Season, Stage


class NewsletterAudienceTest(TestCase):
    def setUp(self):
        self.season = Season.objects.create(year=2099, slug="s", title="S",
                                            is_active=True, is_published=True)
        self.stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.ONLINE, slug="online", title="Отбор",
            starts_at=timezone.now() - timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1), is_published=True,
        )
        self.problem = Problem.objects.create(stage=self.stage, number=1, title="З",
                                              max_score=Decimal(10), status=Problem.Status.APPROVED)

        self.submitted = self._participant("sub@e.ru")
        self.idle = self._participant("idle@e.ru")
        self.stranger = self._participant("stranger@e.ru", register=False)
        self.organizer = User.objects.create_user("org@e.ru", "pass12345",
                                                  role=User.Role.ORGANIZER)
        Submission.objects.create(user=self.submitted, problem=self.problem)

    def _participant(self, email, register=True):
        user = User.objects.create_user(email, "pass12345")
        ParticipantProfile.objects.create(user=user, last_name="Ф", first_name="И")
        if register:
            Registration.objects.create(user=user, season=self.season)
        return user

    def _emails(self, audience, season=None):
        n = Newsletter.objects.create(subject="t", body="b", audience=audience, season=season)
        return set(n.get_recipients().values_list("email", flat=True))

    def test_all_participants_excludes_organizers(self):
        got = self._emails(Newsletter.Audience.ALL_PARTICIPANTS)
        self.assertIn("idle@e.ru", got)
        self.assertNotIn("org@e.ru", got)

    def test_season_participants_excludes_unregistered(self):
        got = self._emails(Newsletter.Audience.SEASON_PARTICIPANTS, self.season)
        self.assertNotIn("stranger@e.ru", got)
        self.assertIn("sub@e.ru", got)

    def test_not_submitted_audience(self):
        got = self._emails(Newsletter.Audience.SEASON_NOT_SUBMITTED, self.season)
        self.assertEqual(got, {"idle@e.ru"})

    def test_submitted_audience(self):
        got = self._emails(Newsletter.Audience.SEASON_SUBMITTED, self.season)
        self.assertEqual(got, {"sub@e.ru"})

    def test_inactive_users_never_receive_mail(self):
        self.idle.is_active = False
        self.idle.save()
        self.assertNotIn("idle@e.ru", self._emails(Newsletter.Audience.ALL_PARTICIPANTS))

    def test_season_audience_without_season_sends_to_nobody(self):
        self.assertEqual(self._emails(Newsletter.Audience.SEASON_PARTICIPANTS), set())


class NewsletterSendingTest(TestCase):
    def setUp(self):
        for i in range(3):
            user = User.objects.create_user(f"u{i}@e.ru", "pass12345")
            ParticipantProfile.objects.create(user=user, last_name="Иванов", first_name="Иван")
        self.newsletter = Newsletter.objects.create(
            subject="Тема", body="Привет, {{ first_name }}!",
            audience=Newsletter.Audience.ALL_PARTICIPANTS,
        )

    def test_queue_creates_one_delivery_per_recipient(self):
        self.assertEqual(queue_newsletter(self.newsletter), 3)
        self.assertEqual(Delivery.objects.count(), 3)
        self.assertEqual(self.newsletter.status, Newsletter.Status.QUEUED)

    def test_queueing_twice_does_not_duplicate(self):
        queue_newsletter(self.newsletter)
        queue_newsletter(self.newsletter)
        self.assertEqual(Delivery.objects.count(), 3)

    def test_sending_delivers_and_marks_done(self):
        queue_newsletter(self.newsletter)
        stats = send_pending()
        self.assertEqual(stats["sent"], 3)
        self.assertEqual(len(mail.outbox), 3)
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, Newsletter.Status.SENT)

    def test_second_send_does_not_resend(self):
        queue_newsletter(self.newsletter)
        send_pending()
        mail.outbox.clear()
        self.assertEqual(send_pending()["sent"], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_batch_limit_is_respected(self):
        queue_newsletter(self.newsletter)
        self.assertEqual(send_pending(limit=2)["sent"], 2)
        self.newsletter.refresh_from_db()
        self.assertEqual(self.newsletter.status, Newsletter.Status.SENDING)

    def test_name_is_substituted(self):
        user = User.objects.get(email="u0@e.ru")
        self.assertEqual(render_body(self.newsletter, user), "Привет, Иван!")

    def test_each_letter_goes_to_one_address_only(self):
        """Адреса школьников не должны светиться друг другу."""
        queue_newsletter(self.newsletter)
        send_pending()
        for message in mail.outbox:
            self.assertEqual(len(message.to), 1)
            self.assertFalse(message.cc)
            self.assertFalse(message.bcc)

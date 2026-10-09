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

    def _emails(self, audience, season=None, venue=None):
        n = Newsletter.objects.create(subject="t", body="b", audience=audience, season=season, venue=venue)
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

    def test_organizers_audience(self):
        from apps.venues.models import Venue
        venue = Venue.objects.create(title="Площадка", region="МСК", city="МСК", address="А", latitude=0, longitude=0)
        venue_mgr = User.objects.create_user("mgr@e.ru", "pass12345", role=User.Role.PARTICIPANT)
        venue.managers.add(venue_mgr)

        got = self._emails(Newsletter.Audience.ORGANIZERS)
        self.assertIn("org@e.ru", got)
        self.assertIn("mgr@e.ru", got)
        self.assertNotIn("idle@e.ru", got)

    def test_admins_audience(self):
        admin_user = User.objects.create_user("admin@e.ru", "pass12345", role=User.Role.ADMIN)
        superuser = User.objects.create_superuser("super@e.ru", "pass12345")

        got = self._emails(Newsletter.Audience.ADMINS)
        self.assertIn("admin@e.ru", got)
        self.assertIn("super@e.ru", got)
        self.assertNotIn("org@e.ru", got)
        self.assertNotIn("idle@e.ru", got)

    def test_venue_audiences(self):
        from apps.venues.models import Venue
        from apps.participation.models import VenueBooking

        v1 = Venue.objects.create(title="П1", region="МСК", city="МСК", address="А1", latitude=0, longitude=0)
        v2 = Venue.objects.create(title="П2", region="МСК", city="МСК", address="А2", latitude=0, longitude=0)

        org1 = User.objects.create_user("org1@e.ru", "pass12345", role=User.Role.ORGANIZER)
        org2 = User.objects.create_user("org2@e.ru", "pass12345", role=User.Role.ORGANIZER)
        v1.managers.add(org1)
        v2.managers.add(org2)

        p1 = self._participant("p1@e.ru")
        p2 = self._participant("p2@e.ru")
        p_cancelled = self._participant("pc@e.ru")

        reg1 = p1.registrations.get(season=self.season)
        reg2 = p2.registrations.get(season=self.season)
        reg_c = p_cancelled.registrations.get(season=self.season)

        VenueBooking.objects.create(registration=reg1, stage=self.stage, venue=v1, status=VenueBooking.Status.CONFIRMED)
        VenueBooking.objects.create(registration=reg2, stage=self.stage, venue=v2, status=VenueBooking.Status.CONFIRMED)
        VenueBooking.objects.create(registration=reg_c, stage=self.stage, venue=v1, status=VenueBooking.Status.CANCELLED)

        # Venue organizers
        got_v1_org = self._emails(Newsletter.Audience.VENUE_ORGANIZERS, venue=v1)
        self.assertEqual(got_v1_org, {"org1@e.ru"})
        self.assertEqual(self._emails(Newsletter.Audience.VENUE_ORGANIZERS, venue=None), set())

        # Venue participants
        got_v1_part = self._emails(Newsletter.Audience.VENUE_PARTICIPANTS, venue=v1)
        self.assertEqual(got_v1_part, {"p1@e.ru"})
        self.assertEqual(self._emails(Newsletter.Audience.VENUE_PARTICIPANTS, venue=None), set())


class NewsletterAdminFormTest(TestCase):
    def setUp(self):
        from apps.mailing.admin import NewsletterAdminForm
        from apps.venues.models import Venue
        self.form_class = NewsletterAdminForm
        self.season = Season.objects.create(year=2099, slug="s", title="S")
        self.venue = Venue.objects.create(title="П", region="МСК", city="МСК", address="А", latitude=0, longitude=0)

    def test_venue_required_for_venue_audiences(self):
        form = self.form_class(data={
            "subject": "Тест",
            "body": "Тест",
            "audience": Newsletter.Audience.VENUE_ORGANIZERS,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("venue", form.errors)

        form_valid = self.form_class(data={
            "subject": "Тест",
            "body": "Тест",
            "audience": Newsletter.Audience.VENUE_ORGANIZERS,
            "venue": self.venue.pk,
            "season": self.season.pk,
        })
        self.assertTrue(form_valid.is_valid())
        # Season is cleared when venue audience is used
        self.assertIsNone(form_valid.cleaned_data["season"])

    def test_season_required_for_season_audiences(self):
        form = self.form_class(data={
            "subject": "Тест",
            "body": "Тест",
            "audience": Newsletter.Audience.SEASON_PARTICIPANTS,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("season", form.errors)

        form_valid = self.form_class(data={
            "subject": "Тест",
            "body": "Тест",
            "audience": Newsletter.Audience.SEASON_PARTICIPANTS,
            "season": self.season.pk,
            "venue": self.venue.pk,
        })
        self.assertTrue(form_valid.is_valid())
        # Venue is cleared when season audience is used
        self.assertIsNone(form_valid.cleaned_data["venue"])

    def test_global_audiences_clear_season_and_venue(self):
        form = self.form_class(data={
            "subject": "Тест",
            "body": "Тест",
            "audience": Newsletter.Audience.ALL_PARTICIPANTS,
            "season": self.season.pk,
            "venue": self.venue.pk,
        })
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data["season"])
        self.assertIsNone(form.cleaned_data["venue"])


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

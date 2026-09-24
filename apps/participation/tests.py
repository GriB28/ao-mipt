"""Запись на площадку: перезапись не плодит дубли, закрытая запись не пускает."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.testing import make_eligible
from apps.participation.models import Registration, VenueBooking, VenueBookingError
from apps.seasons.models import Season, Stage
from apps.venues.models import Venue


class VenueBookingTest(TestCase):
    def setUp(self):
        now = timezone.now()
        self.season = Season.objects.create(year=2099, slug="s", title="S", is_active=True, is_published=True)
        self.stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.OFFLINE, slug="final", title="Финал",
            starts_at=now + timedelta(days=10), ends_at=now + timedelta(days=10, hours=4),
            registration_opens_at=now - timedelta(days=1),
            registration_closes_at=now + timedelta(days=5),
            is_published=True,
        )
        self.venue = Venue.objects.create(
            title="Школа", region="R", city="C", address="A",
            latitude=55.0, longitude=37.0, status=Venue.Status.APPROVED,
        )

    def _registration(self, n):
        user = User.objects.create_user(f"u{n}@b.ru", "pass12345")
        return Registration.objects.create(user=user, season=self.season)

    def test_booking_counts_participants(self):
        for i in range(3):
            VenueBooking.book(self._registration(i), self.stage, self.venue)
        self.assertEqual(self.venue.booked_count(self.stage), 3)

    def test_no_upper_limit_on_bookings(self):
        """Мест не ограничиваем: если придёт много, договариваемся вручную."""
        for i in range(50):
            VenueBooking.book(self._registration(i), self.stage, self.venue)
        self.assertEqual(self.venue.booked_count(self.stage), 50)

    def test_cancelled_booking_is_not_counted(self):
        booking = VenueBooking.book(self._registration(0), self.stage, self.venue)
        VenueBooking.book(self._registration(1), self.stage, self.venue)
        booking.status = VenueBooking.Status.CANCELLED
        booking.save()
        self.assertEqual(self.venue.booked_count(self.stage), 1)

    def test_rebooking_moves_participant_instead_of_duplicating(self):
        reg = self._registration(0)
        other = Venue.objects.create(
            title="Школа 2", region="R", city="C", address="B",
            latitude=56.0, longitude=38.0, status=Venue.Status.APPROVED,
        )
        VenueBooking.book(reg, self.stage, self.venue)
        VenueBooking.book(reg, self.stage, other)
        self.assertEqual(VenueBooking.objects.filter(registration=reg, stage=self.stage).count(), 1)
        self.assertEqual(self.venue.booked_count(self.stage), 0)
        self.assertEqual(other.booked_count(self.stage), 1)

    def test_booking_fails_when_registration_closed(self):
        self.stage.registration_closes_at = timezone.now() - timedelta(days=1)
        self.stage.save()
        with self.assertRaises(VenueBookingError):
            VenueBooking.book(self._registration(0), self.stage, self.venue)

    def test_booking_fails_for_unapproved_venue(self):
        self.venue.status = Venue.Status.PENDING
        self.venue.save()
        with self.assertRaises(VenueBookingError):
            VenueBooking.book(self._registration(0), self.stage, self.venue)


class VenueBookingViewTest(TestCase):
    """Кнопка «Записаться» на странице площадки — то, чего раньше не было."""

    def setUp(self):
        now = timezone.now()
        self.season = Season.objects.create(year=2098, slug="s98", title="S", is_active=True, is_published=True)
        self.stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.OFFLINE, slug="ochny", title="Очный тур",
            starts_at=now + timedelta(days=10), ends_at=now + timedelta(days=12),
            registration_opens_at=now - timedelta(days=1),
            registration_closes_at=now + timedelta(days=5),
            is_published=True,
        )
        self.venue = Venue.objects.create(
            title="Школа", region="R", city="C", address="A",
            latitude=55.0, longitude=37.0, status=Venue.Status.APPROVED,
        )
        self.venue.seasons.add(self.season)
        self.user = make_eligible(User.objects.create_user("kid@b.ru", "olymp12345"))

    def _book(self):
        return self.client.post(reverse("venues:book", args=[self.venue.pk]))

    def test_anonymous_is_sent_to_login(self):
        response = self._book()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertEqual(VenueBooking.objects.count(), 0)

    def test_participant_can_book(self):
        self.client.force_login(self.user)
        self._book()
        self.assertEqual(self.venue.booked_count(self.stage), 1)

    def test_booking_creates_season_registration_if_missing(self):
        """Человек мог зарегистрироваться раньше, чем сезон стал активным."""
        self.client.force_login(self.user)
        self._book()
        self.assertTrue(Registration.objects.filter(user=self.user, season=self.season).exists())

    def test_second_booking_moves_instead_of_adding(self):
        other = Venue.objects.create(
            title="Школа 2", region="R", city="C", address="B",
            latitude=56.0, longitude=38.0, status=Venue.Status.APPROVED,
        )
        other.seasons.add(self.season)
        self.client.force_login(self.user)
        self._book()
        self.client.post(reverse("venues:book", args=[other.pk]))
        self.assertEqual(self.venue.booked_count(self.stage), 0)
        self.assertEqual(other.booked_count(self.stage), 1)

    def test_cancel_frees_the_place(self):
        self.client.force_login(self.user)
        self._book()
        self.client.post(reverse("venues:cancel_booking", args=[self.venue.pk]))
        self.assertEqual(self.venue.booked_count(self.stage), 0)

    def test_closed_registration_shows_error_and_books_nothing(self):
        self.stage.registration_closes_at = timezone.now() - timedelta(hours=1)
        self.stage.save()
        self.client.force_login(self.user)
        self._book()
        self.assertEqual(VenueBooking.objects.count(), 0)

    def test_get_does_not_book(self):
        """Запись меняет данные, поэтому только POST — иначе её сделает любой краулер."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("venues:book", args=[self.venue.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(VenueBooking.objects.count(), 0)

    def test_button_visible_on_venue_page(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("venues:detail", args=[self.venue.pk])).content.decode()
        self.assertIn("Записаться", html)
        self.assertNotIn("в разработке", html)


class VenueLedgerTest(TestCase):
    """Ведомость площадки: список участников, баллы, итоги, публикация."""

    def setUp(self):
        from apps.contest.models import Problem, Score
        from apps.seasons.models import Season, Stage

        now = timezone.now()
        self.season = Season.objects.create(year=2097, slug="s97", title="S",
                                            is_active=True, is_published=True)
        self.stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.OFFLINE, slug="ochny", title="Очный тур",
            starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
            registration_opens_at=now - timedelta(days=2), is_published=True,
        )
        self.problems = [
            Problem.objects.create(stage=self.stage, number=n, title=f"Задача {n}",
                                   status=Problem.Status.APPROVED)
            for n in (1, 2)
        ]
        self.organizer = User.objects.create_user("led@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER)
        self.stranger = User.objects.create_user("str@e.ru", "olymp12345",
                                                 role=User.Role.ORGANIZER)
        self.venue = Venue.objects.create(
            title="Школа", region="R", city="C", address="A",
            latitude=55.0, longitude=37.0, status=Venue.Status.APPROVED,
        )
        self.venue.managers.add(self.organizer)
        self.venue.seasons.add(self.season)

        self.kid = User.objects.create_user("kid7@e.ru", "olymp12345")
        self.registration = Registration.objects.create(user=self.kid, season=self.season)
        VenueBooking.book(self.registration, self.stage, self.venue)

        self.Score = Score

    def _url(self, name):
        return reverse(f"venues:{name}", args=[self.venue.pk])

    def test_manager_sees_who_signed_up(self):
        self.client.force_login(self.organizer)
        html = self.client.get(self._url("participants")).content.decode()
        self.assertIn(self.kid.email, html)

    def test_other_organizer_is_refused(self):
        """Чужая площадка — чужие персональные данные."""
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self._url("participants")).status_code, 403)

    def test_participant_is_refused(self):
        self.client.force_login(self.kid)
        self.assertEqual(self.client.get(self._url("participants")).status_code, 403)

    def test_scores_are_saved_per_problem(self):
        self.client.force_login(self.organizer)
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": "7",
            f"score-{self.registration.pk}-{self.problems[1].pk}": "3.5",
        })
        points = {s.problem_id: s.points for s in self.Score.objects.all()}
        self.assertEqual(points[self.problems[0].pk], Decimal("7"))
        self.assertEqual(points[self.problems[1].pk], Decimal("3.5"))

    def test_comma_is_accepted_as_a_decimal_point(self):
        self.client.force_login(self.organizer)
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": "3,5",
        })
        self.assertEqual(self.Score.objects.get().points, Decimal("3.5"))

    def test_empty_cell_erases_the_score(self):
        self.client.force_login(self.organizer)
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": "7"})
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": ""})
        self.assertFalse(self.Score.objects.exists())

    def test_results_table_sums_and_ranks(self):
        self.client.force_login(self.organizer)
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": "7",
            f"score-{self.registration.pk}-{self.problems[1].pk}": "3",
        })
        response = self.client.get(self._url("results"))
        self.assertEqual(response.context["rows"][0]["total"], Decimal("10"))

    def test_scores_stay_hidden_until_an_admin_publishes_them(self):
        self.client.force_login(self.organizer)
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": "7"})

        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:my_submissions")).content.decode()
        self.assertNotIn("Результаты", html)

    def test_admin_button_opens_the_scores(self):
        admin = User.objects.create_user("adm@e.ru", "olymp12345", role=User.Role.ADMIN)
        self.venue.managers.add(admin)
        self.client.force_login(self.organizer)
        self.client.post(self._url("participants"), {
            f"score-{self.registration.pk}-{self.problems[0].pk}": "7"})

        self.client.force_login(admin)
        self.client.post(self._url("publish_results"))
        self.stage.refresh_from_db()
        self.assertTrue(self.stage.results_published)

        self.client.force_login(self.kid)
        html = self.client.get(reverse("contest:my_submissions")).content.decode()
        self.assertIn("Результаты", html)

    def test_organizer_cannot_publish_results(self):
        """Публикация — решение администратора, а не одной площадки."""
        self.client.force_login(self.organizer)
        response = self.client.post(self._url("publish_results"))
        self.assertEqual(response.status_code, 403)
        self.stage.refresh_from_db()
        self.assertFalse(self.stage.results_published)


class BookingRulesTest(TestCase):
    """Одна площадка на участника, и запись не закрывается после тура."""

    def setUp(self):
        from apps.seasons.models import Season, Stage

        now = timezone.now()
        self.season = Season.objects.create(year=2096, slug="s96", title="S",
                                            is_active=True, is_published=True)
        # Тур уже прошёл, дата закрытия записи не задана.
        self.stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.OFFLINE, slug="ochny", title="Очный тур",
            starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=9),
            registration_opens_at=now - timedelta(days=20), is_published=True,
        )
        self.venues = [
            Venue.objects.create(title=f"Школа {i}", region="R", city="C", address=f"A{i}",
                                 latitude=55.0 + i, longitude=37.0, status=Venue.Status.APPROVED)
            for i in (1, 2)
        ]
        for venue in self.venues:
            venue.seasons.add(self.season)
        self.kid = make_eligible(User.objects.create_user("kid8@e.ru", "olymp12345"))

    def test_registration_stays_open_after_the_round(self):
        """На площадку приходят без регистрации — их заводят задним числом."""
        self.assertTrue(self.stage.registration_is_open)

    def test_closing_date_still_works_when_set(self):
        self.stage.registration_closes_at = timezone.now() - timedelta(days=1)
        self.stage.save()
        self.assertFalse(self.stage.registration_is_open)

    def test_participant_ends_up_on_exactly_one_venue(self):
        self.client.force_login(self.kid)
        for venue in self.venues:
            self.client.post(reverse("venues:book", args=[venue.pk]))

        bookings = VenueBooking.objects.filter(registration__user=self.kid).exclude(
            status=VenueBooking.Status.CANCELLED
        )
        self.assertEqual(bookings.count(), 1)
        self.assertEqual(bookings.first().venue, self.venues[1])

    def test_organizer_does_not_book_places(self):
        organizer = User.objects.create_user("o8@e.ru", "olymp12345", role=User.Role.ORGANIZER)
        self.client.force_login(organizer)
        response = self.client.post(reverse("venues:book", args=[self.venues[0].pk]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(VenueBooking.objects.count(), 0)


class VenueManagementTest(TestCase):
    """Правка своей площадки, контакты и письмо участникам."""

    def setUp(self):
        from apps.seasons.models import Season, Stage

        now = timezone.now()
        self.season = Season.objects.create(year=2095, slug="s95", title="S",
                                            is_active=True, is_published=True)
        self.stage = Stage.objects.create(
            season=self.season, kind=Stage.Kind.OFFLINE, slug="ochny", title="Очный тур",
            starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1),
            registration_opens_at=now - timedelta(days=2), is_published=True,
        )
        self.organizer = User.objects.create_user("man@e.ru", "olymp12345",
                                                  role=User.Role.ORGANIZER)
        self.venue = Venue.objects.create(
            title="Школа", region="Москва", city="Москва", address="A",
            latitude=55.7, longitude=37.6, status=Venue.Status.APPROVED,
            contact_name="Иванов", contact_phone="+7 900 000-00-00",
        )
        self.venue.managers.add(self.organizer)
        self.venue.seasons.add(self.season)

        self.kid = User.objects.create_user("kid5@e.ru", "olymp12345")
        registration = Registration.objects.create(user=self.kid, season=self.season)
        VenueBooking.book(registration, self.stage, self.venue)

    def _form_data(self, **extra):
        return {
            "title": "Школа", "region": "Москва", "city": "Москва", "address": "A",
            "latitude": "55.7", "longitude": "37.6",
            "description": "Вход со двора, сбор в 9:30.",
            "contact_name": "Иванов", "contact_phone": "+7 900 000-00-00",
            "contact_telegram": "", "contact_email": "",
        } | extra

    def test_manager_can_fix_the_description(self):
        self.client.force_login(self.organizer)
        self.client.post(reverse("venues:edit", args=[self.venue.pk]), self._form_data())
        self.venue.refresh_from_db()
        self.assertIn("Вход со двора", self.venue.description)

    def test_editing_does_not_send_the_venue_back_to_moderation(self):
        """Исправленная опечатка не должна убирать площадку с карты."""
        self.client.force_login(self.organizer)
        self.client.post(reverse("venues:edit", args=[self.venue.pk]), self._form_data())
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.status, Venue.Status.APPROVED)

    def test_stranger_cannot_edit(self):
        other = User.objects.create_user("oth@e.ru", "olymp12345", role=User.Role.ORGANIZER)
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("venues:edit", args=[self.venue.pk])).status_code, 403
        )

    def test_region_must_come_from_the_list(self):
        self.client.force_login(self.organizer)
        self.client.post(reverse("venues:edit", args=[self.venue.pk]),
                         self._form_data(region="Мордор"))
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.region, "Москва")

    def test_phone_or_telegram_required(self):
        self.client.force_login(self.organizer)
        response = self.client.post(reverse("venues:edit", args=[self.venue.pk]),
                                    self._form_data(contact_phone="", contact_telegram=""))
        self.assertFormError(response.context["form"], "contact_phone",
                             "Укажите телефон или Telegram — хотя бы один способ связи.")

    def test_telegram_alone_is_enough(self):
        self.client.force_login(self.organizer)
        self.client.post(reverse("venues:edit", args=[self.venue.pk]),
                         self._form_data(contact_phone="", contact_telegram="@ivanov"))
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.contact_telegram, "@ivanov")

    def test_point_on_the_map_is_required(self):
        self.client.force_login(self.organizer)
        response = self.client.post(reverse("venues:edit", args=[self.venue.pk]),
                                    self._form_data(latitude="", longitude=""))
        self.assertIn("Отметьте площадку на карте", response.content.decode())

    def test_mail_reaches_only_this_venue(self):
        from django.core import mail

        from apps.mailing.models import Newsletter

        # Участник другой площадки письма получать не должен.
        other_venue = Venue.objects.create(
            title="Школа 2", region="Москва", city="Москва", address="B",
            latitude=55.8, longitude=37.7, status=Venue.Status.APPROVED,
        )
        other_venue.seasons.add(self.season)
        stranger = User.objects.create_user("far@e.ru", "olymp12345")
        VenueBooking.book(
            Registration.objects.create(user=stranger, season=self.season),
            self.stage, other_venue,
        )

        self.client.force_login(self.organizer)
        self.client.post(reverse("venues:mail", args=[self.venue.pk]),
                         {"subject": "Сбор в 9:30", "body": "Здравствуйте, {{ first_name }}!"})

        self.assertEqual(Newsletter.objects.count(), 1)
        self.assertEqual([m.to for m in mail.outbox], [[self.kid.email]])

    def test_mail_substitutes_the_name(self):
        from django.core import mail

        from apps.accounts.models import ParticipantProfile

        ParticipantProfile.objects.create(user=self.kid, last_name="Тестов", first_name="Пётр",
                                          school="Ш", city="Москва", region="Москва")
        self.client.force_login(self.organizer)
        self.client.post(reverse("venues:mail", args=[self.venue.pk]),
                         {"subject": "Тема", "body": "Здравствуйте, {{ first_name }}!"})
        self.assertIn("Пётр", mail.outbox[0].body)

    def test_stranger_cannot_write_to_someone_elses_participants(self):
        other = User.objects.create_user("oth2@e.ru", "olymp12345", role=User.Role.ORGANIZER)
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("venues:mail", args=[self.venue.pk])).status_code, 403
        )

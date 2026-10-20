"""Тесты площадок: выгрузка данных участников в Excel, права доступа."""

import io
from datetime import date, timedelta

import openpyxl
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DocumentType, ParticipantProfile, User
from apps.participation.models import Registration, VenueBooking
from apps.seasons.models import Season, Stage
from apps.venues.export import format_passport_data
from apps.venues.models import Venue


class VenueExportUnitTests(TestCase):
    """Модульные тесты форматирования паспортных данных и генерации файла Excel."""

    def test_format_passport_data_empty_or_none(self):
        self.assertEqual(format_passport_data(None), "")
        profile = ParticipantProfile()
        self.assertEqual(format_passport_data(profile), "")

    def test_format_passport_data_passport_rf_complete(self):
        user = User.objects.create_user("u1@b.ru", "pass123")
        profile = ParticipantProfile.objects.create(
            user=user,
            doc_type=DocumentType.PASSPORT_RF,
            doc_series="4510",
            doc_number="123456",
            doc_issued_at=date(2020, 2, 1),
            doc_issued_by="ГУ МВД по г. Москве",
            doc_division_code="770-001",
        )
        expected = "Паспорт РФ: серия 4510 № 123456, выдан 01.02.2020, ГУ МВД по г. Москве, код подразделения 770-001"
        self.assertEqual(format_passport_data(profile), expected)

    def test_format_passport_data_birth_cert(self):
        user = User.objects.create_user("u2@b.ru", "pass123")
        profile = ParticipantProfile.objects.create(
            user=user,
            doc_type=DocumentType.BIRTH_CERT,
            doc_series="IV-МЮ",
            doc_number="654321",
            doc_issued_at=date(2014, 5, 15),
            doc_issued_by="Орган ЗАГС г. Москвы",
        )
        expected = "Свидетельство о рождении: серия IV-МЮ № 654321, выдано 15.05.2014, Орган ЗАГС г. Москвы"
        self.assertEqual(format_passport_data(profile), expected)

    def test_format_passport_data_foreign(self):
        user = User.objects.create_user("u3@b.ru", "pass123")
        profile = ParticipantProfile.objects.create(
            user=user,
            doc_type=DocumentType.FOREIGN,
            doc_number="AB987654",
            doc_issued_at=date(2022, 1, 10),
            doc_issued_by="МВД РК",
        )
        expected = "Документ другой страны: № AB987654, выдан 10.01.2022, МВД РК"
        self.assertEqual(format_passport_data(profile), expected)

    def test_format_passport_data_partial(self):
        user = User.objects.create_user("u4@b.ru", "pass123")
        profile = ParticipantProfile.objects.create(
            user=user,
            doc_type=DocumentType.PASSPORT_RF,
            doc_series="4510",
            doc_number="123456",
        )
        self.assertEqual(format_passport_data(profile), "Паспорт РФ: серия 4510 № 123456")


class VenueExportViewTests(TestCase):
    """Интеграционные тесты выгрузки участников площадки в Excel и прав доступа."""

    def setUp(self):
        now = timezone.now()
        self.season = Season.objects.create(
            year=2099, slug="s2099", title="Сезон 2099", is_active=True, is_published=True
        )
        self.stage = Stage.objects.create(
            season=self.season,
            kind=Stage.Kind.OFFLINE,
            slug="offline-final",
            title="Очный тур",
            starts_at=now + timedelta(days=5),
            ends_at=now + timedelta(days=5, hours=4),
            registration_opens_at=now - timedelta(days=2),
            registration_closes_at=now + timedelta(days=3),
            is_published=True,
        )
        self.organizer = User.objects.create_user("org@b.ru", "pass12345", role=User.Role.ORGANIZER)
        self.other_organizer = User.objects.create_user(
            "other_org@b.ru", "pass12345", role=User.Role.ORGANIZER
        )
        self.admin = User.objects.create_user("admin@b.ru", "pass12345", role=User.Role.ADMIN, is_staff=True)
        self.participant = User.objects.create_user("part@b.ru", "pass12345", role=User.Role.PARTICIPANT)

        self.venue = Venue.objects.create(
            title="Лицей № 1580",
            region="Москва",
            city="Москва",
            address="ул. Талалихина, 1к1",
            latitude=55.73,
            longitude=37.67,
            status=Venue.Status.APPROVED,
        )
        self.venue.managers.add(self.organizer)
        self.venue.seasons.add(self.season)

        # Участник 1 с заполненным профилем
        self.user1 = User.objects.create_user("ivanov@b.ru", "pass12345")
        ParticipantProfile.objects.create(
            user=self.user1,
            last_name="Иванов",
            first_name="Иван",
            middle_name="Иванович",
            school="ГБОУ Лицей № 1502",
            doc_type=DocumentType.PASSPORT_RF,
            doc_series="4510",
            doc_number="123456",
            doc_issued_at=date(2020, 1, 15),
            doc_issued_by="ГУ МВД г. Москвы",
            doc_division_code="770-001",
        )
        reg1 = Registration.objects.create(user=self.user1, season=self.season)
        VenueBooking.objects.create(
            registration=reg1, stage=self.stage, venue=self.venue, status=VenueBooking.Status.BOOKED
        )

        # Участник 2 без профиля
        self.user2 = User.objects.create_user(
            "petrov@b.ru", "pass12345", first_name="Пётр", last_name="Петров"
        )
        reg2 = Registration.objects.create(user=self.user2, season=self.season)
        VenueBooking.objects.create(
            registration=reg2, stage=self.stage, venue=self.venue, status=VenueBooking.Status.BOOKED
        )

        # Отменённая запись (не должна попасть в выгрузку)
        self.user_cancelled = User.objects.create_user("canc@b.ru", "pass12345")
        reg_canc = Registration.objects.create(user=self.user_cancelled, season=self.season)
        VenueBooking.objects.create(
            registration=reg_canc, stage=self.stage, venue=self.venue, status=VenueBooking.Status.CANCELLED
        )

    def test_anonymous_redirected_to_login(self):
        url = reverse("venues:export", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_participant_forbidden(self):
        self.client.force_login(self.participant)
        url = reverse("venues:export", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_other_organizer_forbidden(self):
        self.client.force_login(self.other_organizer)
        url = reverse("venues:export", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_venue_manager_can_export(self):
        self.client.force_login(self.organizer)
        url = reverse("venues:export", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn(f'filename="venue-{self.venue.pk}-participants.xlsx"', response["Content-Disposition"])

        # Проверяем содержимое Excel
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws = wb.active
        self.assertEqual(ws.title, "Участники")

        # Заголовки
        headers = [cell.value for cell in ws[1]]
        self.assertEqual(headers, ["ФИО", "Паспортные данные", "Школа", "Адрес точки проведения"])

        # Строки с данными
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        # Ожидаем 2 записи (отменённая не попадает)
        self.assertEqual(len(rows), 2)

        # Проверяем данные участника 1
        row_ivanov = next(r for r in rows if "Иванов Иван Иванович" in r[0])
        self.assertIn("Паспорт РФ: серия 4510 № 123456", row_ivanov[1])
        self.assertIn("код подразделения 770-001", row_ivanov[1])
        self.assertEqual(row_ivanov[2], "ГБОУ Лицей № 1502")
        self.assertEqual(row_ivanov[3], self.venue.address)

        # Проверяем участника 2 (без профиля ПД и школы)
        row_petrov = next(r for r in rows if "Петров" in r[0] or "petrov@b.ru" in r[0])
        self.assertIn(row_petrov[1], ("", None))
        self.assertIn(row_petrov[2], ("", None))
        self.assertEqual(row_petrov[3], self.venue.address)

        # Участника с отменённой записью быть не должно
        self.assertFalse(any("canc@b.ru" in str(r[0]) for r in rows))

    def test_admin_can_export(self):
        self.client.force_login(self.admin)
        url = reverse("venues:export", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_button_present_on_detail_page_for_manager(self):
        self.client.force_login(self.organizer)
        url = reverse("venues:detail", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("venues:export", args=[self.venue.pk]))
        self.assertContains(response, "Выгрузить в Excel")

    def test_button_not_present_for_participant(self):
        self.client.force_login(self.participant)
        url = reverse("venues:detail", args=[self.venue.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("venues:export", args=[self.venue.pk]))



class VenueStagePassedTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(
            year=2099, slug="s2099", title="Сезон 2099", is_active=True, is_published=True
        )
        self.admin = User.objects.create_user(
            "admin_user@b.ru", "pass12345", role=User.Role.ADMIN, is_staff=True, is_superuser=True
        )
        self.venue = Venue.objects.create(
            title="Тестовая площадка",
            region="Москва",
            city="Москва",
            address="ул. Примерная, 10",
            latitude=55.75,
            longitude=37.62,
            status=Venue.Status.APPROVED,
            stage_passed=False,
        )
        self.venue.seasons.add(self.season)

    def test_default_stage_passed_is_false(self):
        self.assertFalse(self.venue.stage_passed)

    def test_as_geojson_feature_contains_stage_passed(self):
        feature = self.venue.as_geojson_feature()
        self.assertIn("stage_passed", feature["properties"])
        self.assertFalse(feature["properties"]["stage_passed"])

        self.venue.stage_passed = True
        self.venue.save()
        feature_updated = self.venue.as_geojson_feature()
        self.assertTrue(feature_updated["properties"]["stage_passed"])

    def test_venues_geojson_endpoint_returns_stage_passed(self):
        res = self.client.get(reverse("venues:geojson"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        props = next(f["properties"] for f in data["features"] if f["properties"]["id"] == self.venue.pk)
        self.assertFalse(props["stage_passed"])

        self.venue.stage_passed = True
        self.venue.save()
        res = self.client.get(reverse("venues:geojson"))
        data = res.json()
        props = next(f["properties"] for f in data["features"] if f["properties"]["id"] == self.venue.pk)
        self.assertTrue(props["stage_passed"])

    def test_detail_page_shows_passed_badge_when_stage_passed(self):
        url = reverse("venues:detail", args=[self.venue.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "Этап прошёл")

        self.venue.stage_passed = True
        self.venue.save()
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Этап прошёл")

    def test_admin_changelist_shows_stage_passed(self):
        self.client.force_login(self.admin)
        url = reverse("admin:venues_venue_changelist")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Этап прошёл")
        self.assertContains(res, f'name="form-0-stage_passed"')

    def test_admin_actions_mark_stage_passed(self):
        self.client.force_login(self.admin)
        url = reverse("admin:venues_venue_changelist")

        # Mark stage passed
        post_data = {
            "action": "mark_stage_passed",
            "_selected_action": [str(self.venue.pk)],
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)
        self.venue.refresh_from_db()
        self.assertTrue(self.venue.stage_passed)

        # Mark stage not passed
        post_data["action"] = "mark_stage_not_passed"
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)
        self.venue.refresh_from_db()
        self.assertFalse(self.venue.stage_passed)

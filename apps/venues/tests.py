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


class OfflineGradingAndScansTests(TestCase):
    """Тесты ведомости очного тура, переключения комплектов и загрузки сканов."""

    def setUp(self):
        from decimal import Decimal
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.contest.models import Problem, Score

        self.Decimal = Decimal
        self.SimpleUploadedFile = SimpleUploadedFile
        self.Problem = Problem
        self.Score = Score

        now = timezone.now()
        self.season = Season.objects.create(
            year=2099, slug="s2099", title="Сезон 2099", is_active=True, is_published=True
        )
        self.stage = Stage.objects.create(
            season=self.season,
            kind=Stage.Kind.OFFLINE,
            slug="offline-final",
            title="Очный тур",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=2),
            is_published=True,
            order=1,
        )
        self.venue = Venue.objects.create(
            title="МФТИ КПМ",
            city="Долгопрудный",
            address="Первомайская 7",
            latitude=55.93,
            longitude=37.52,
            status=Venue.Status.APPROVED,
            default_variant=1,
            event_date=date(2099, 10, 15),
        )
        self.venue.seasons.add(self.season)

        self.organizer = User.objects.create_user("org_offline@b.ru", "pass12345", role=User.Role.ORGANIZER)
        self.participant1 = User.objects.create_user("part1@b.ru", "pass12345", role=User.Role.PARTICIPANT)
        self.participant2 = User.objects.create_user("part2@b.ru", "pass12345", role=User.Role.PARTICIPANT)

        reg1 = Registration.objects.create(user=self.participant1, season=self.season)
        self.booking1 = VenueBooking.objects.create(
            registration=reg1,
            stage=self.stage,
            venue=self.venue,
            status=VenueBooking.Status.CONFIRMED,
        )

        reg2 = Registration.objects.create(user=self.participant2, season=self.season)
        self.booking2 = VenueBooking.objects.create(
            registration=reg2,
            stage=self.stage,
            venue=self.venue,
            status=VenueBooking.Status.CONFIRMED,
        )

        # Задачи: 1.1, 1.2 (Комплект 1), 2.1, 2.2 (Комплект 2)
        self.p1_1 = Problem.objects.create(
            stage=self.stage, number="1.1", title="Задача 1.1",
            max_score=Decimal("10"), status=Problem.Status.APPROVED,
        )
        self.p1_2 = Problem.objects.create(
            stage=self.stage, number="1.2", title="Задача 1.2",
            max_score=Decimal("10"), status=Problem.Status.APPROVED,
        )
        self.p2_1 = Problem.objects.create(
            stage=self.stage, number="2.1", title="Задача 2.1",
            max_score=Decimal("10"), status=Problem.Status.APPROVED,
        )
        self.p2_2 = Problem.objects.create(
            stage=self.stage, number="2.2", title="Задача 2.2",
            max_score=Decimal("10"), status=Problem.Status.APPROVED,
        )

    def test_manager_sees_tabs_participant_does_not(self):
        # Обычный участник: нет вкладок
        self.client.force_login(self.participant1)
        resp = self.client.get(reverse("venues:map"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "sub-tabs-nav")
        self.assertNotContains(resp, "Проверка задач")
        self.assertNotContains(resp, "Загрузка скана работы")

        # Организатор: видит вкладки
        self.client.force_login(self.organizer)
        resp = self.client.get(reverse("venues:map"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "sub-tabs-nav")
        self.assertContains(resp, "Проверка задач")
        self.assertContains(resp, "Загрузка скана работы")

    def test_offline_grading_ajax_scores_and_variant_deactivation(self):
        self.client.force_login(self.organizer)
        save_url = reverse("venues:save_scores")

        # Ставим балл 8.5 за 1.1 (Комплект 1)
        resp = self.client.post(
            save_url,
            {"booking_id": self.booking1.pk, "problem_id": self.p1_1.pk, "points": "8.5"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["total"], "8.5")

        # Ставим балл 7.0 за 2.1 (Комплект 2) — при активном комплекте 1 он должен быть skipped
        resp = self.client.post(
            save_url,
            {"booking_id": self.booking1.pk, "problem_id": self.p2_1.pk, "points": "7"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], "8.5")  # 7 не входит в сумму!

        s1_1 = self.Score.objects.get(registration=self.booking1.registration, problem=self.p1_1)
        self.assertFalse(s1_1.is_skipped)
        s2_1 = self.Score.objects.get(registration=self.booking1.registration, problem=self.p2_1)
        self.assertTrue(s2_1.is_skipped)

        # Переключаем комплект участника на 2
        resp = self.client.post(
            save_url,
            {"booking_id": self.booking1.pk, "variant": "2"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["variant"], 2)
        self.assertEqual(data["total"], "7")  # теперь в сумме только 2.1!

        s1_1.refresh_from_db()
        s2_1.refresh_from_db()
        self.assertTrue(s1_1.is_skipped)
        self.assertFalse(s2_1.is_skipped)

    def test_offline_scan_upload_download_and_permissions(self):
        self.client.force_login(self.organizer)
        upload_url = reverse("venues:upload_work_scan")

        # Не-PDF отклоняется
        txt_file = self.SimpleUploadedFile("work.txt", b"not a pdf", content_type="text/plain")
        resp = self.client.post(upload_url, {"booking_id": self.booking1.pk, "work_scan": txt_file})
        self.booking1.refresh_from_db()
        self.assertFalse(bool(self.booking1.work_scan))

        # Валидный PDF загружается
        pdf_file = self.SimpleUploadedFile("work.pdf", b"%PDF-1.4 sample content", content_type="application/pdf")
        resp = self.client.post(
            upload_url,
            {"booking_id": self.booking1.pk, "work_scan": pdf_file, "variant": "2", "held_at": "2099-10-16"},
        )
        self.booking1.refresh_from_db()
        self.assertTrue(bool(self.booking1.work_scan))
        self.assertEqual(self.booking1.variant, 2)
        self.assertEqual(str(self.booking1.held_at), "2099-10-16")

        scan_url = self.booking1.get_scan_url()

        # Организатор может скачать/просмотреть скан
        resp = self.client.get(scan_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

        # Участник до публикации результатов получает 404
        self.client.force_login(self.participant1)
        resp = self.client.get(scan_url)
        self.assertEqual(resp.status_code, 404)

        # Публикуем результаты
        self.stage.results_published = True
        self.stage.save()

        # Теперь участник видит свой скан
        resp = self.client.get(scan_url)
        self.assertEqual(resp.status_code, 200)

        # Чужой участник не видит
        self.client.force_login(self.participant2)
        resp = self.client.get(scan_url)
        self.assertEqual(resp.status_code, 404)

        # Удаление скана организатором
        self.client.force_login(self.organizer)
        del_url = reverse("venues:delete_work_scan", args=[self.booking1.pk])
        resp = self.client.post(del_url)
        self.booking1.refresh_from_db()
        self.assertFalse(bool(self.booking1.work_scan))


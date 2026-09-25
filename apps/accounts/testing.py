"""Помощники для тестов других приложений."""

from datetime import date

from django.core.files.base import ContentFile

from .models import ConsentDocument, DocumentType, ParticipantProfile


def make_eligible(user, **profile_fields):
    """Сделать участника допущенным: почта, полная анкета, загруженное согласие.

    Тестам записи на площадку и сдачи решений важна их собственная
    логика, а не три шага до участия — те проверяются в accounts.
    """
    user.email_confirmed = True
    user.save(update_fields=["email_confirmed"])
    defaults = {
        "last_name": "Тестов", "first_name": "Пётр", "birth_date": date(2010, 1, 1),
        "birth_place": "г. Москва",
        "grade": 10, "school": "Школа", "city": "Москва", "region": "Москва",
        "phone": "+7 900 000-00-00", "telegram": "@testov", "doc_type": DocumentType.PASSPORT_RF,
        "doc_series": "0000", "doc_number": "000000", "doc_issued_at": date(2024, 1, 10),
        "doc_issued_by": "МВД", "doc_division_code": "770-001", "reg_address": "Москва",
    } | profile_fields
    profile, _ = ParticipantProfile.objects.update_or_create(user=user, defaults=defaults)
    ConsentDocument.objects.create(user=user, data=profile.consent_data(),
                                   file=ContentFile(b"%PDF", name="c.pdf"), original_name="c.pdf")
    return user

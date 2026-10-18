"""Выгрузка участников площадки в Excel."""

import io
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def format_passport_data(profile):
    """Строка паспортных данных участника для таблицы.

    Например: «Паспорт РФ: серия 4510 № 123456, выдан 01.02.2020, Отделом УФМС, код подразделения 770-001».
    Корректно обрабатывает пустые или частично заполненные поля.
    """
    if not profile:
        return ""

    label = profile.get_doc_type_display() if profile.doc_type else ""
    parts = []

    series = (profile.doc_series or "").strip()
    number = (profile.doc_number or "").strip()
    if series and number:
        parts.append(f"серия {series} № {number}")
    elif number:
        parts.append(f"№ {number}")
    elif series:
        parts.append(f"серия {series}")

    issued_parts = []
    verb = "выдано" if profile.doc_type == "birth_cert" else "выдан"
    issued_date = (
        profile.doc_issued_at.strftime("%d.%m.%Y") if isinstance(profile.doc_issued_at, date) else ""
    )
    issued_by = (profile.doc_issued_by or "").strip()

    if issued_date and issued_by:
        issued_parts.append(f"{verb} {issued_date}, {issued_by}")
    elif issued_date:
        issued_parts.append(f"{verb} {issued_date}")
    elif issued_by:
        issued_parts.append(f"{verb} {issued_by}")

    if issued_parts:
        parts.append(", ".join(issued_parts))

    division_code = (profile.doc_division_code or "").strip()
    if division_code:
        parts.append(f"код подразделения {division_code}")

    details = ", ".join(parts)
    if label and details:
        return f"{label}: {details}"
    if label:
        return label
    return details


def generate_venue_participants_excel(venue, bookings):
    """Сформировать Excel-книгу (.xlsx) со списком участников площадки."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Участники"

    headers = ["ФИО", "Паспортные данные", "Адрес точки проведения"]
    ws.append(headers)

    header_font = Font(name="Calibri", size=11, bold=True)
    header_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="left", vertical="center")

    for booking in bookings:
        user = booking.registration.user
        profile = getattr(user, "profile", None)
        fio = profile.full_name if (profile and profile.full_name) else (user.get_full_name() or user.email)
        passport = format_passport_data(profile)
        address = venue.address or ""
        ws.append([fio, passport, address])

    for row in ws.iter_rows(min_row=2, max_row=max(ws.max_row, 2), min_col=1, max_col=3):
        for cell in row:
            cell.alignment = Alignment(vertical="center")

    min_widths = [30, 45, 35]
    for col_idx, min_w in enumerate(min_widths, 1):
        col_letter = get_column_letter(col_idx)
        max_len = max(len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(1, ws.max_row + 1))
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, min_w), 70)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

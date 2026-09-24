"""
Бланк согласия на обработку ПД в PDF.

Собирается из данных анкеты: школьник скачивает его, печатает,
подписывает и загружает скан обратно. Если участнику нет 18, бланк
подписывают двое — участник и законный представитель; данные
представителя вписываются от руки, на сайте их нет.

Текст берётся со страницы consent-form-minor / consent-form-adult,
если её завели в админке, иначе — из apps/core/legal_templates.py.
Подстановки {{ имя }} заменяются простой заменой строк, а не шаблонами
Django: текст пишут в админке, и исполнять в нём ничего не нужно.
"""

import html
import io
import re
from pathlib import Path

import nh3
from django.conf import settings
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core import legal_templates

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_fonts_ready = False


def _register_fonts():
    """DejaVu лежит в репозитории: у стандартных шрифтов PDF нет кириллицы."""
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", FONT_DIR / "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold",
                                  italic="DejaVu", boldItalic="DejaVu-Bold")
    _fonts_ready = True


def _date(value):
    return value.strftime("%d.%m.%Y") if value else "________"


def _document(profile):
    """«паспорт РФ серия 4510 № 123456, выдан 01.02.2020, ГУ МВД …» — внутри фразы, со строчной."""
    label = profile.get_doc_type_display()
    label = label[:1].lower() + label[1:]
    series = f"серия {profile.doc_series} " if profile.doc_series else ""
    issued = "выдано" if profile.doc_type == "birth_cert" else "выдан"
    return (f"{label} {series}№ {profile.doc_number}, {issued} "
            f"{_date(profile.doc_issued_at)}, {profile.doc_issued_by}")


def template_text(minor: bool) -> str:
    from apps.content.models import Page

    slug = "consent-form-minor" if minor else "consent-form-adult"
    page = Page.objects.filter(slug=slug).first()
    if page and page.body.strip():
        return page.body
    return legal_templates.CONSENT_FORM_MINOR if minor else legal_templates.CONSENT_FORM_ADULT


def fill(text: str, values: dict) -> str:
    """Подставить данные в {{ имя }}. Значения экранируются: это ввод участника.

    Неизвестная подстановка (например, из старой редакции текста в админке)
    становится пустой строкой — её заполнят от руки, а не увидят «{{ … }}».
    """
    def replace(match):
        key = match.group(1)
        return html.escape(values[key]) if key in values else legal_templates.BLANK
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, text)


def values_for(profile) -> dict:
    user = profile.user
    return {
        "participant_name": profile.full_name,
        "participant_birth_date": _date(profile.birth_date),
        "participant_document": _document(profile),
        "participant_address": profile.reg_address,
        "operator": legal_templates.CONSENT_OPERATOR,
        "contact_email": settings.CONTACT_EMAIL,
        "today": _date(timezone.localdate()),
        "email": user.email,
    }


def _blocks(text):
    """HTML из админки → абзацы для reportlab.

    Reportlab понимает только <b>, <i>, <br/> внутри абзаца, поэтому
    сначала оставляем безопасный минимум, потом режем по абзацам.
    """
    text = nh3.clean(text, tags={"p", "b", "strong", "i", "em", "br", "li", "h2", "h3"},
                     attributes={})
    text = re.sub(r"<(/?)strong>", r"<\1b>", text)
    text = re.sub(r"<(/?)em>", r"<\1i>", text)
    text = re.sub(r"<br\s*/?>", "<br/>", text)
    parts = re.split(r"</?(?:p|li|h2|h3)>", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]


def build(profile) -> bytes:
    """PDF-бланк для этой анкеты. Для несовершеннолетнего — от представителя."""
    _register_fonts()
    minor = profile.is_minor
    values = values_for(profile)

    body = ParagraphStyle("body", fontName="DejaVu", fontSize=10, leading=13.5,
                          spaceAfter=5, alignment=4)  # 4 — по ширине
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor="#555555",
                           alignment=0)

    title = ParagraphStyle("title", parent=body, fontSize=11.5, leading=15, alignment=1,
                           spaceAfter=10)
    # Строки для заполнения от руки: интервал шире, чтобы уместился почерк.
    handwritten = ParagraphStyle("handwritten", parent=body, leading=21, alignment=0)
    blocks = _blocks(fill(template_text(minor), values))
    story = []
    for i, block in enumerate(blocks):
        # Первый абзац — заголовок бланка: по центру, а не по ширине.
        style = title if i == 0 else handwritten if "______" in block else body
        # Подсказка под строкой — «(кем выдан)» — мелко, чтобы не спорила с почерком.
        block = re.sub(r"(^|<br/>)\s*(\([^()<]{3,80}\))\s*(?=<br/>|$)",
                       r'\1<font size="7" color="#666666">\2</font>', block)
        story.append(Paragraph(block, style))
    story.append(Spacer(1, 6 * mm))

    # Подписывают оба: участник и, если ему нет 18, законный представитель.
    # ФИО представителя на сайте нет — строка для него пустая.
    rows = []
    if minor:
        rows.append(["Законный представитель:", "______________", "/ " + "_" * 26 + " /"])
    rows.append(["Участник:", "______________", f"/ {profile.full_name} /"])
    rows.append(["Дата:", "«____» ____________ 20____ г.", ""])
    sign = Table(rows, colWidths=[55 * mm, 45 * mm, 75 * mm])
    sign.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
                              ("FONTSIZE", (0, 0), (-1, -1), 10),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                              ("SPAN", (1, -1), (2, -1))]))
    story.append(sign)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"Бланк сформирован на сайте олимпиады {values['today']} для учётной записи "
        f"{html.escape(values['email'])} (№ {profile.user_id}). Распечатайте, подпишите "
        "и загрузите скан или фото в личном кабинете.", small))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title="Согласие на обработку персональных данных",
                            author="Аэрокосмическая олимпиада МФТИ")
    doc.build(story)
    return buffer.getvalue()

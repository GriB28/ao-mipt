"""
Бланк согласия на обработку ПД в PDF — по шаблону оргкомитета.

Собирается из анкеты: школьник скачивает его, печатает, подписывает и
загружает скан обратно. Сверху — данные участника (и законного
представителя, если участнику нет 18) в строках с подписями под ними,
как в бумажном шаблоне; дальше — текст согласия; внизу — ФИО, подпись и
дата каждого, кто подписывает. От руки — только подписи и даты.

Текст берётся со страницы consent-form-minor / consent-form-adult, если
её завели в админке, иначе — из apps/core/legal_templates.py.
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
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.core import legal_templates

FONT_DIR = Path(__file__).resolve().parent / "fonts"
PAGE_WIDTH = 175 * mm  # A4 минус поля
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
    return value.strftime("%d.%m.%Y") if value else ""


def _passport_line(profile, prefix):
    """«серия 4510 № 123456, выдан 01.02.2020, ГУ МВД …, код подразделения 770-001»."""
    series = getattr(profile, f"{prefix}doc_series")
    parts = [f"серия {series} № {getattr(profile, f'{prefix}doc_number')}" if series
             else f"№ {getattr(profile, f'{prefix}doc_number')}"]
    kind = getattr(profile, f"{prefix}doc_type")
    parts.append(f"{'выдано' if kind == 'birth_cert' else 'выдан'} "
                 f"{_date(getattr(profile, f'{prefix}doc_issued_at'))}, "
                 f"{getattr(profile, f'{prefix}doc_issued_by')}")
    code = getattr(profile, f"{prefix}doc_division_code")
    if code:
        parts.append(f"код подразделения {code}")
    label = getattr(profile, f"get_{prefix}doc_type_display")()
    return f"{label}: " + ", ".join(parts)


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
    """Подстановки для текста согласия (все — строки)."""
    return {
        "participant_name": profile.full_name,
        "participant_birth_date": _date(profile.birth_date),
        "participant_document": _passport_line(profile, "") if profile.doc_type else "",
        "participant_address": profile.reg_address,
        "parent_name": profile.parent_full_name,
        "parent_document": _passport_line(profile, "parent_") if profile.parent_doc_type else "",
        "parent_address": profile.parent_reg_address,
        "operator": legal_templates.CONSENT_OPERATOR,
        "contact_email": settings.CONTACT_EMAIL,
        "today": _date(timezone.localdate()),
        "email": profile.user.email,
    }


def _blocks(text):
    """HTML из админки → абзацы для reportlab.

    Reportlab понимает только <b>, <i>, <br/> внутри абзаца, поэтому
    сначала оставляем безопасный минимум, потом режем по абзацам. Пункт
    списка становится абзацем с тире — как в бумажном шаблоне.
    """
    text = nh3.clean(text, tags={"p", "b", "strong", "i", "em", "br", "li", "ul", "ol", "h2", "h3"},
                     attributes={})
    text = re.sub(r"<(/?)strong>", r"<\1b>", text)
    text = re.sub(r"<(/?)em>", r"<\1i>", text)
    text = re.sub(r"<br\s*/?>", "<br/>", text)
    text = re.sub(r"</?[uo]l>", "", text)
    text = re.sub(r"<li>", "<li>– ", text)
    parts = re.split(r"</?(?:p|li|h2|h3)>", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]


class _Styles:
    def __init__(self, size=8.8):
        self.title = ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=11.5, leading=15,
                                    alignment=1)
        self.body = ParagraphStyle("body", fontName="DejaVu", fontSize=size, leading=size * 1.25,
                                   spaceAfter=3, alignment=4)  # 4 — по ширине
        self.item = ParagraphStyle("item", parent=self.body, spaceAfter=0, alignment=0)
        self.value = ParagraphStyle("value", fontName="DejaVu", fontSize=min(size, 9),
                                    leading=min(size, 9) * 1.22)
        self.caption = ParagraphStyle("caption", fontName="DejaVu", fontSize=7, leading=9,
                                      alignment=1, textColor="#555555")
        self.small = ParagraphStyle("small", fontName="DejaVu", fontSize=7.5, leading=9.5,
                                    textColor="#555555")


def _fields(rows, styles):
    """Строки «значение над чертой, подпись под чертой», как в бумажном бланке.

    rows — список строк; строка — список пар (подпись, значение, доля ширины).
    """
    story = []
    for row in rows:
        widths = [PAGE_WIDTH * share for _, _, share in row]
        values = [Paragraph(html.escape(value or ""), styles.value) for _, value, _ in row]
        captions = [Paragraph(caption, styles.caption) for caption, _, _ in row]
        table = Table([values, captions], colWidths=widths)
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, "#000000"),
            ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 3),
        ]))
        story.append(table)
    return story


def _signatures(signers, styles):
    """ФИО | подпись | дата — для каждого, кто подписывает."""
    rows, style = [], [
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]
    for i, (name, caption) in enumerate(signers):
        top = i * 2
        rows.append([Paragraph(html.escape(name), styles.value), "", ""])
        rows.append([Paragraph(caption, styles.caption), Paragraph("подпись", styles.caption),
                     Paragraph("дата", styles.caption)])
        style += [("LINEBELOW", (0, top), (-1, top), 0.6, "#000000"),
                  ("TOPPADDING", (0, top), (-1, top), 12),
                  ("BOTTOMPADDING", (0, top + 1), (-1, top + 1), 6)]
    table = Table(rows, colWidths=[PAGE_WIDTH * 0.55, PAGE_WIDTH * 0.27, PAGE_WIDTH * 0.18])
    table.setStyle(TableStyle(style))
    return table


#: Размеры основного шрифта, которые пробуем по очереди.
FONT_SIZES = (8.8, 8.4, 8.0, 7.6, 7.2)


def build(profile) -> bytes:
    """PDF-бланк для этой анкеты. Для несовершеннолетнего — вместе с представителем.

    Бланк должен уместиться на одну страницу: скан загружается одним
    файлом, и вторая страница с подписями потерялась бы. Длинный адрес или
    «кем выдан» могут столкнуть подписи вниз — тогда собираем заново
    шрифтом чуть мельче.
    """
    _register_fonts()
    for size in FONT_SIZES:
        pdf, pages = _render(profile, _Styles(size))
        if pages == 1:
            break
    return pdf


def _render(profile, styles):
    """Собрать PDF; вернуть (байты, число страниц)."""
    _register_fonts()
    minor = profile.is_minor
    values = values_for(profile)

    story = [Paragraph("СОГЛАСИЕ", styles.title),
             Paragraph("на обработку персональных данных", styles.title),
             Spacer(1, 3 * mm)]

    story += _fields([
        [("ФИО", profile.full_name, 0.72), ("Дата рождения", _date(profile.birth_date), 0.28)],
        [("Тип документа", profile.get_doc_type_display(), 0.34),
         ("Серия", profile.doc_series, 0.18), ("Номер", profile.doc_number, 0.22),
         ("Дата выдачи", _date(profile.doc_issued_at), 0.26)],
        [("Кем выдан", profile.doc_issued_by, 0.76),
         ("Код подразделения", profile.doc_division_code, 0.24)],
        [("Адрес регистрации по паспорту", profile.reg_address, 1.0)],
    ], styles)

    if minor:
        story.append(Paragraph("И законный представитель Субъекта персональных данных "
                               "на основании п. 1 ст. 64 Семейного кодекса РФ", styles.body))
        story += _fields([
            [("ФИО представителя", profile.parent_full_name, 1.0)],
            [("Паспортные данные: серия, номер, кем и когда выдан, код подразделения",
              values["parent_document"], 1.0)],
            [("Адрес регистрации по паспорту", profile.parent_reg_address, 1.0)],
        ], styles)
    story.append(Spacer(1, 2 * mm))

    # Пункты списка подряд собираем в две колонки: бланк должен уместиться
    # на одну страницу — скан загружается одним файлом.
    items = []
    for block in _blocks(fill(template_text(minor), values)) + [""]:
        if block.startswith("– "):
            items.append(Paragraph(block, styles.item))
            continue
        if items:
            half = (len(items) + 1) // 2
            left, right = items[:half], items[half:] + [""] * (2 * half - len(items))
            columns = Table(list(zip(left, right, strict=True)), colWidths=[PAGE_WIDTH / 2] * 2)
            columns.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                                         ("TOPPADDING", (0, 0), (-1, -1), 0),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                         ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [columns, Spacer(1, 1.5 * mm)]
            items = []
        if block:
            story.append(Paragraph(block, styles.body))

    signers = [(profile.full_name, "ФИО Субъекта персональных данных")]
    if minor:
        signers.append((profile.parent_full_name, "ФИО законного представителя"))
    story.append(KeepTogether([
        Spacer(1, 3 * mm),
        _signatures(signers, styles),
        Spacer(1, 5 * mm),
        Paragraph(
            f"Бланк сформирован на сайте олимпиады {values['today']} для учётной записи "
            f"{html.escape(values['email'])} (№ {profile.user_id}). Распечатайте, подпишите "
            "и загрузите скан или фото в личном кабинете.", styles.small),
    ]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=15 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title="Согласие на обработку персональных данных",
                            author="Аэрокосмическая олимпиада МФТИ")
    doc.build(story)
    return buffer.getvalue(), doc.page

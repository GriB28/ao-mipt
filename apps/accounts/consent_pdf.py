"""
Бланк согласий в PDF: две страницы — два самостоятельных документа.

Стр. 1 — согласие на обработку персональных данных, стр. 2 — согласие
на распространение (по закону оно оформляется отдельно от других). У
каждого свой заголовок, свои подписи, и каждый помещается на свою
страницу. Собирается из анкеты: школьник скачивает бланк, печатает,
подписывает обе страницы и загружает скан или фото обеих страниц.

Сверху — данные участника в строках с подписями под ними, как в бумажном
шаблоне; дальше — текст; внизу — ФИО, подпись и дата каждого, кто
подписывает. Если участнику нет 18, законный представитель вписывает
свои данные от руки в пустые строки — на сайте их нет, — и подписывают
оба: участник и представитель.

Текст берётся со страниц consent-form-* (стр. 1) и consent-dist-* (стр. 2),
если их завели в админке, иначе — из apps/core/legal_templates.py.
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
    PageBreak,
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
    """Liberation Serif — метрический двойник Times New Roman.

    Сам Times New Roman — шрифт Microsoft, класть его в репозиторий и
    образ нельзя. Liberation Serif совпадает с ним по ширинам символов
    и почти неотличим на вид, с кириллицей, под свободной лицензией
    SIL OFL (fonts/LICENSE). У стандартных шрифтов PDF кириллицы нет.
    """
    global _fonts_ready
    if _fonts_ready:
        return
    for style, suffix in (("", "Regular"), ("-Bold", "Bold"), ("-Italic", "Italic"),
                          ("-BoldItalic", "BoldItalic")):
        pdfmetrics.registerFont(TTFont(f"Serif{style}", FONT_DIR / f"LiberationSerif-{suffix}.ttf"))
    pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-Bold",
                                  italic="Serif-Italic", boldItalic="Serif-BoldItalic")
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


#: Документ бланка → (слаг страницы в админке без суффикса, текст по умолчанию).
_TEXTS = {
    "form": ("consent-form", legal_templates.CONSENT_FORM_MINOR, legal_templates.CONSENT_FORM_ADULT),
    "dist": ("consent-dist", legal_templates.CONSENT_DIST_MINOR, legal_templates.CONSENT_DIST_ADULT),
}


def template_text(minor: bool, kind: str = "form") -> str:
    """Текст документа: kind="form" — согласие на обработку, "dist" — на распространение."""
    from apps.content.models import Page

    prefix, for_minor, for_adult = _TEXTS[kind]
    page = Page.objects.filter(slug=f"{prefix}-{'minor' if minor else 'adult'}").first()
    if page and page.body.strip():
        return page.body
    return for_minor if minor else for_adult


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
        "participant_birth_place": profile.birth_place,
        "participant_document": _passport_line(profile, "") if profile.doc_type else "",
        "participant_address": profile.reg_address,
        "operator": legal_templates.CONSENT_OPERATOR,
        # Для текстов, переписанных в админке до октября 2026: адрес сайта
        # теперь вписан в сам текст (legal_templates.SITE).
        "site": f"сайте олимпиады {legal_templates.SITE}",
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
    """Как в бумажных бланках: основной текст прямой, подписи под строками —
    мелким курсивом (не серым: серый плохо пропечатывается и сканируется)."""

    def __init__(self, size=10.5):
        self.title = ParagraphStyle("title", fontName="Serif-Bold", fontSize=13, leading=16,
                                    alignment=1)
        self.body = ParagraphStyle("body", fontName="Serif", fontSize=size, leading=size * 1.15,
                                   spaceAfter=2, alignment=4)  # 4 — по ширине
        self.item = ParagraphStyle("item", parent=self.body, spaceAfter=0, alignment=0)
        self.value = ParagraphStyle("value", fontName="Serif", fontSize=min(size, 11),
                                    leading=min(size, 11) * 1.2)
        self.caption = ParagraphStyle("caption", fontName="Serif-Italic", fontSize=7.5, leading=8.5,
                                      alignment=1)
        self.small = ParagraphStyle("small", fontName="Serif-Italic", fontSize=8.5, leading=10)
        self.heading = ParagraphStyle("heading", fontName="Serif-Bold", fontSize=min(size, 10.5),
                                      leading=min(size, 10.5) * 1.15, spaceBefore=1, spaceAfter=0)


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
            ("BOTTOMPADDING", (0, 1), (-1, 1), 1.5),
        ]))
        story.append(table)
    return story


#: Высота строки для заполнения от руки — чтобы уместился почерк.
HANDWRITING_LINE = 8 * mm


def _blank_fields(rows, styles):
    """Пустые строки для заполнения от руки, подпись — под последней строкой поля.

    rows — список (подпись, сколько строк).
    """
    story = []
    for caption, lines in rows:
        cells = [[""] for _ in range(lines)] + [[Paragraph(caption, styles.caption)]]
        table = Table(cells, colWidths=[PAGE_WIDTH],
                      rowHeights=[HANDWRITING_LINE] * lines + [None])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Serif"),
            ("LINEBELOW", (0, 0), (-1, lines - 1), 0.6, "#000000"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 1.5),
        ]))
        story.append(table)
    return story


def _signatures(signers, styles):
    """ФИО | подпись | дата — для каждого, кто подписывает."""
    rows, style = [], [
        ("FONTNAME", (0, 0), (-1, -1), "Serif"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]
    for i, (name, caption) in enumerate(signers):
        top = i * 2
        # Пустое имя — строка для заполнения от руки (ФИО родителя).
        rows.append([Paragraph(html.escape(name), styles.value), "", ""])
        rows.append([Paragraph(caption, styles.caption), Paragraph("подпись", styles.caption),
                     Paragraph("дата", styles.caption)])
        style += [("LINEBELOW", (0, top), (-1, top), 0.6, "#000000"),
                  ("TOPPADDING", (0, top), (-1, top), 14),
                  ("BOTTOMPADDING", (0, top + 1), (-1, top + 1), 3)]
    table = Table(rows, colWidths=[PAGE_WIDTH * 0.55, PAGE_WIDTH * 0.27, PAGE_WIDTH * 0.18])
    table.setStyle(TableStyle(style))
    return table


#: Подпись под строкой документа — у участника и у представителя одна и та же.
DOCUMENT_CAPTION = ("Документ, удостоверяющий личность: вид, серия, номер, "
                    "кем и когда выдан, код подразделения")

#: Основание полномочий (п. 2 ч. 4 ст. 9 152-ФЗ). Представителем может быть
#: не только родитель, поэтому документ вписывается от руки.
AUTHORITY_CAPTION = ("Документ, подтверждающий полномочия законного представителя "
                     "(например, свидетельство о рождении участника)")

#: Размеры основного шрифта, которые пробуем по очереди.
FONT_SIZES = (10.5, 10, 9.5, 9, 8.5, 8)


def build(profile) -> bytes:
    """PDF для этой анкеты: согласие на обработку и на распространение.

    Каждый документ должен уместиться на свою страницу — иначе подписи
    уедут на следующую, отдельно от текста. Длинный адрес или «кем выдан»
    могут столкнуть подписи вниз — тогда документ собирается шрифтом
    чуть мельче.
    """
    story = _fit(_processing, profile) + [PageBreak()] + _fit(_distribution, profile)
    pdf, _ = _pdf(story)
    return pdf


def _fit(make, profile):
    """История документа самым крупным шрифтом, при котором он на одной странице."""
    _register_fonts()  # абзацы разбирают шрифт уже при создании
    for size in FONT_SIZES:
        story = make(profile, _Styles(size))
        _, pages = _pdf(make(profile, _Styles(size)))
        if pages == 1:
            break
    return story


def _pdf(story):
    """Собрать PDF; вернуть (байты, число страниц)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=15 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title="Согласие на обработку персональных данных",
                            author="Аэрокосмическая олимпиада МФТИ")
    doc.build(story)
    return buffer.getvalue(), doc.page


def _title(lines, styles):
    return [*(Paragraph(line, styles.title) for line in lines), Spacer(1, 3 * mm)]


def _representative(styles, full=True):
    """Строки представителя — от руки. В согласии на распространение
    (full=False) паспорт и адрес не нужны: приказ Роскомнадзора № 18 их
    не требует, а на стр. 1 они уже есть."""
    rows = [("ФИО законного представителя (полностью)", 1)]
    if full:
        rows += [("Паспорт: серия, номер, кем и когда выдан, код подразделения", 2),
                 ("Адрес регистрации по паспорту", 1)]
    rows.append((AUTHORITY_CAPTION, 1))
    return [Paragraph("Законный представитель участника", styles.heading),
            *_blank_fields(rows, styles)]


def _text(text, values, styles):
    """Текст документа. Пункты списка подряд — в две колонки, так бланк
    короче и помещается на страницу."""
    story, items = [], []
    for block in _blocks(fill(text, values)) + [""]:
        if block.startswith("– "):
            items.append(Paragraph(block, styles.item))
            continue
        if items:
            half = (len(items) + 1) // 2
            left, right = items[:half], items[half:] + [""] * (2 * half - len(items))
            columns = Table(list(zip(left, right, strict=True)), colWidths=[PAGE_WIDTH / 2] * 2)
            columns.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Serif"),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                                         ("TOPPADDING", (0, 0), (-1, -1), 0),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                         ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [columns, Spacer(1, 1.5 * mm)]
            items = []
        if block:
            story.append(Paragraph(block, styles.body))
    return story


def _signed(profile, values, styles):
    """Подписи: первым — участник, он даёт согласие; затем представитель."""
    signers = [(profile.full_name, "ФИО участника (субъекта персональных данных)")]
    if profile.is_minor:
        signers.append(("", "ФИО законного представителя"))
    return KeepTogether([
        Spacer(1, 3 * mm),
        _signatures(signers, styles),
        Spacer(1, 2 * mm),
        Paragraph(
            f"Сформировано на сайте олимпиады {values['today']}, учётная запись "
            f"{html.escape(values['email'])} (№ {profile.user_id}).", styles.small),
    ])


def _processing(profile, styles):
    """Стр. 1 — согласие на обработку персональных данных."""
    minor = profile.is_minor
    values = values_for(profile)
    story = _title(["СОГЛАСИЕ", "на обработку персональных данных"], styles)
    if minor:
        story.append(Paragraph("Участник олимпиады (субъект персональных данных)", styles.heading))
    story += _fields([
        [("ФИО", profile.full_name, 0.46), ("Дата рождения", _date(profile.birth_date), 0.18),
         ("Место рождения", profile.birth_place, 0.36)],
        [(DOCUMENT_CAPTION, values["participant_document"], 1.0)],
        [("Адрес регистрации по паспорту", profile.reg_address, 1.0)],
    ], styles)
    if minor:
        story += _representative(styles)
    story.append(Spacer(1, 2 * mm))
    story += _text(template_text(minor, "form"), values, styles)
    story.append(_signed(profile, values, styles))
    return story


def _distribution(profile, styles):
    """Стр. 2 — согласие на распространение (приказ Роскомнадзора № 18):
    ФИО и контакт участника, условия и запреты — от руки по желанию."""
    minor = profile.is_minor
    values = values_for(profile)
    story = _title(["СОГЛАСИЕ", "на обработку персональных данных, разрешённых",
                    "субъектом персональных данных для распространения"], styles)
    if minor:
        story.append(Paragraph("Участник олимпиады (субъект персональных данных)", styles.heading))
    # Контактной информации хватает одной: e-mail есть у каждого участника.
    story += _fields([[("ФИО", profile.full_name, 0.6), ("E-mail", profile.user.email, 0.4)]], styles)
    if minor:
        story += _representative(styles, full=False)
    story.append(Spacer(1, 2 * mm))
    story += _text(template_text(minor, "dist"), values, styles)
    story += _blank_fields([(legal_templates.PROHIBITIONS, 2),
                            (legal_templates.TRANSFER_CONDITIONS, 1)], styles)
    story.append(_signed(profile, values, styles))
    return story

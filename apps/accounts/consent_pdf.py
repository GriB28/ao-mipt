"""
Бланк согласия на обработку ПД в PDF — по шаблону оргкомитета.

Собирается из анкеты: школьник скачивает его, печатает, подписывает и
загружает скан обратно. Сверху — данные участника в строках с подписями
под ними, как в бумажном шаблоне; дальше — текст согласия; внизу — ФИО,
подпись и дата каждого, кто подписывает.

Если участнику нет 18, согласие даёт законный представитель (родитель):
свои ФИО, паспорт и адрес он вписывает от руки в пустые строки — на
сайте его данных нет, — и подписывают бланк двое: родитель и участник.

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
        "operator": legal_templates.CONSENT_OPERATOR,
        # Где публикуются результаты: правила Роскомнадзора к согласию на
        # распространение требуют назвать информационный ресурс.
        "site": f"сайте олимпиады {settings.SITE_URL}" if settings.SITE_URL else "сайте олимпиады",
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

#: Размеры основного шрифта, которые пробуем по очереди.
FONT_SIZES = (10.5, 10, 9.5, 9, 8.5, 8)


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

    # Документ участника и представителя — одной строкой и под одной
    # подписью: так бланк читается одинаково сверху донизу.
    if minor:
        story.append(Paragraph("Участник олимпиады (субъект персональных данных)", styles.heading))
    story += _fields([
        [("ФИО", profile.full_name, 0.72), ("Дата рождения", _date(profile.birth_date), 0.28)],
        [(DOCUMENT_CAPTION, values["participant_document"], 1.0)],
        [("Адрес регистрации по паспорту", profile.reg_address, 1.0)],
    ], styles)

    if minor:
        # Основание полномочий — обязательная часть согласия представителя
        # (п. 2 ч. 4 ст. 9 152-ФЗ). Согласие дают родители: их полномочия
        # следуют из закона.
        story.append(Paragraph(
            "Законный представитель Участника <i>(на основании п. 1 ст. 64 "
            "Семейного кодекса РФ)</i>", styles.heading))
        # Данные родителя — от руки: на сайте их нет.
        story += _blank_fields([
            ("ФИО законного представителя (полностью)", 1),
            ("Паспорт: серия, номер, кем и когда выдан, код подразделения", 2),
            ("Адрес регистрации по паспорту", 2),
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
            columns.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Serif"),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                                         ("TOPPADDING", (0, 0), (-1, -1), 0),
                                         ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                         ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [columns, Spacer(1, 1.5 * mm)]
            items = []
        if block:
            story.append(Paragraph(block, styles.body))

    # Первым подписывает участник — согласие даёт он, затем представитель.
    if minor:
        signers = [(profile.full_name, "ФИО участника (субъекта персональных данных)"),
                   ("", "ФИО законного представителя")]
    else:
        signers = [(profile.full_name, "ФИО участника")]
    story.append(KeepTogether([
        Spacer(1, 3 * mm),
        _signatures(signers, styles),
        Spacer(1, 2 * mm),
        Paragraph(
            f"Сформировано на сайте олимпиады {values['today']}, учётная запись "
            f"{html.escape(values['email'])} (№ {profile.user_id}).", styles.small),
    ]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=15 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title="Согласие на обработку персональных данных",
                            author="Аэрокосмическая олимпиада МФТИ")
    doc.build(story)
    return buffer.getvalue(), doc.page

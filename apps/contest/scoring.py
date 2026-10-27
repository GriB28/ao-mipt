"""
Подсчёт итогов.

Одно место, где складываются баллы, — и это сделано намеренно.
Задачи не равнозначны: у одной максимум 10, у другой 15, а туры между
собой тоже взвешиваются не поровну. Как именно — решим позже, когда
будут результаты первого отбора.

Пока сумма прямая, но считается только здесь: когда появятся веса,
править придётся одну функцию, а не пять шаблонов и три вьюхи.
Ни в шаблонах, ни во вьюхах складывать баллы напрямую нельзя.
"""

from decimal import Decimal

DASH_CHARS = set("-–—―−‒‑‐˗﹣－﹘")
CANONICAL_DASH = "–"


def is_dash(val) -> bool:
    """Проверяет, является ли значение любой формой прочерка."""
    if val is None:
        return False
    s = str(val).strip()
    return bool(s) and all(ch in DASH_CHARS for ch in s)


def format_points(val) -> str:
    """10.00 → «10», 7.50 → «7.5», None → «»."""
    if val is None:
        return ""
    return str(int(val)) if val == val.to_integral() else f"{val:.2f}".rstrip("0").rstrip(".")


def format_cell_score(val) -> str:
    """Отображение балла в ведомостях организаторов.

    0 баллов отображается как канонический прочерк «–» (en-dash),
    не проверенная / не сданная задача — как пустая строка «».
    """
    if val is None:
        return ""
    if val == 0:
        return CANONICAL_DASH
    return format_points(val)



def problem_weight(problem) -> Decimal:
    """Вес задачи в сумме тура.

    Сейчас все задачи входят с весом 1: шкалу задаёт максимальный балл.
    Здесь появится настоящее взвешивание, когда его определят.
    """
    return Decimal(1)


def total(pairs) -> Decimal:
    """
    Сумма по парам (задача, балл).

    Незаполненные баллы (None) пропускаются: «не проверено» — это не ноль,
    и подменять одно другим нельзя, иначе недопроверенная работа выглядит
    как решённая на ноль.
    """
    result = Decimal(0)
    for problem, points in pairs:
        if points is None:
            continue
        result += Decimal(points) * problem_weight(problem)
    return result

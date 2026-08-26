# app/core/dates.py
"""Приведение дат из источника к date.

Колонки в Macro объявлены как DATE, но в MySQL часть из них DATETIME, и драйвер
возвращает datetime. Сравнение или вычитание такого значения с date падает с
TypeError, причём только на боевых данных — в тестах на SQLite значения
приходят уже как date. Поэтому всё, что пришло из источника, прогоняем здесь.
"""

from datetime import date, datetime


def to_date(value):
    """datetime, date или строка -> date. Мусор и None -> None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None

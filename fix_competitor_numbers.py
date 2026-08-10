"""Разовая чистка числовых полей конкурентов.

SQLite не проверяет типы, поэтому импорт из Excel мог записать в Float/Integer
колонки текст ('41,33', '1 250', 'нет данных'). Такие значения ломали карту
(JS-блок со списком ЖК) и карточку сравнения. Скрипт приводит их к числам,
нечисловой мусор обнуляет (None).

Запуск:  python fix_competitor_numbers.py
"""
from app import create_app
from app.core.extensions import db
from app.models.competitor_models import Competitor, CompetitorHistory
from app.services.competitor_service import _to_float, _to_int

FLOAT_FIELDS = ['lat', 'lng', 'ceiling_height', 'avg_area', 'avg_price_sqm', 'avg_bottom_price']
INT_FIELDS = ['units_count', 'sold_count']


def _clean(obj, float_fields, int_fields):
    """Возвращает список исправленных полей объекта."""
    fixed = []
    for field in float_fields:
        old = getattr(obj, field, None)
        new = _to_float(old)
        if new != old:
            setattr(obj, field, new)
            fixed.append(f"{field}: {old!r} -> {new!r}")
    for field in int_fields:
        old = getattr(obj, field, None)
        new = _to_int(old)
        if new != old:
            setattr(obj, field, new)
            fixed.append(f"{field}: {old!r} -> {new!r}")
    return fixed


def run():
    app = create_app()
    with app.app_context():
        total = 0

        for comp in Competitor.query.all():
            fixed = _clean(comp, FLOAT_FIELDS, INT_FIELDS)
            if fixed:
                total += 1
                print(f"[{comp.id}] {comp.name}: " + '; '.join(fixed))

        for entry in CompetitorHistory.query.all():
            fixed = _clean(entry, ['avg_price_sqm', 'avg_bottom_price'], INT_FIELDS)
            if fixed:
                total += 1
                print(f"[history {entry.id}] " + '; '.join(fixed))

        db.session.commit()
        print(f"Исправлено записей: {total}")


if __name__ == '__main__':
    run()

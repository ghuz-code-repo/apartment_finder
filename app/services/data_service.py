# app/services/data_service.py
import time
from sqlalchemy import distinct, and_
from ..core.extensions import db
from ..core.db_utils import get_mysql_session, get_default_session
from app.models.estate_models import EstateSell, EstateHouse
from app.models.exclusion_models import ExcludedSell
from app.models.planning_models import PropertyType
from sqlalchemy.orm import joinedload
import math


# --- ИЗМЕНЕНИЕ: Мы создаем свой собственный класс Pagination ---
# Он ведет себя так же, как и тот, что ожидает Flask,
# но позволяет нам создавать его вручную.

class ManualPagination:
    """Простая замена Pagination, которую можно создать вручную."""

    def __init__(self, page, per_page, total, items):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.items = items

    @property
    def pages(self):
        """Общее количество страниц."""
        if self.per_page == 0:
            return 0
        return int(math.ceil(self.total / float(self.per_page)))

    @property
    def has_prev(self):
        """True, если есть предыдущая страница."""
        return self.page > 1

    @property
    def has_next(self):
        """True, если есть следующая страница."""
        return self.page < self.pages

    @property
    def prev_num(self):
        """Номер предыдущей страницы."""
        return self.page - 1

    @property
    def next_num(self):
        """Номер следующей страницы."""
        return self.page + 1

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        """Логика для итератора страниц (скопирована из Flask-SQLAlchemy)."""
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
                    (self.page - left_current <= num <= self.page + right_current) or \
                    num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


# --- КОНЕЦ НОВОГО КЛАССА ---


def get_sells_with_house_info(page, per_page, complex_filter=None, floor_filter=None, rooms_filter=None):
    """
    Получает предложения о продаже для конкретной страницы.
    Использует ManualPagination.
    """
    print(
        f"\n[DATA SERVICE DEBUG] ManualPagination (Стр: {page}, Фильтры: ЖК='{complex_filter}', Этаж='{floor_filter}', Комн='{rooms_filter}')")
    start_time = time.time()

    mysql_session = None

    try:
        mysql_session = get_mysql_session()
        default_session = get_default_session()

        query = mysql_session.query(EstateSell).options(
            joinedload(EstateSell.house, innerjoin=False)  # LEFT JOIN
        ).order_by(EstateSell.id.desc())

        filters = []

        excluded_ids = default_session.scalars(db.select(ExcludedSell.sell_id)).all()
        if excluded_ids:
            filters.append(EstateSell.id.notin_(excluded_ids))

        valid_statuses = ["Маркетинговый резерв", "Подбор"]
        filters.append(EstateSell.estate_sell_status_name.in_(valid_statuses))

        if complex_filter and complex_filter != 'all':
            filters.append(EstateHouse.complex_name == complex_filter)

        if floor_filter and floor_filter.isdigit():
            filters.append(EstateSell.estate_floor == int(floor_filter))

        if rooms_filter and rooms_filter.isdigit():
            filters.append(EstateSell.estate_rooms == int(rooms_filter))

        if filters:
            query = query.filter(and_(*filters))

        # 3. Получаем ОБЩЕЕ количество
        total = query.count()
        print(f"[DATA SERVICE DEBUG] Найдено записей (COUNT): {total}")

        # 4. Получаем ОБЪЕКТЫ для этой страницы
        items = query.offset((page - 1) * per_page).limit(per_page).all()

        end_time = time.time()
        duration = round(end_time - start_time, 2)
        print(f"[DATA SERVICE DEBUG] ✔️ Запрос (ручной) выполнен. Найдено: {total}. (за {duration} сек.)")

        mysql_session.close()

        # 6. --- ИСПРАВЛЕНИЕ: Используем наш класс ManualPagination ---
        pagination = ManualPagination(page=page, per_page=per_page, total=total, items=items)

        return pagination

    except Exception as e:
        print(f"[DATA SERVICE DEBUG] ❌ ОШИБКА (ManualPagination) при запросе данных: {e}")
        if mysql_session:
            mysql_session.close()

        # Возвращаем пустую пагинацию
        return ManualPagination(page=page, per_page=per_page, total=0, items=[])


def get_all_complex_names():
    """Возвращает список уникальных названий ЖК из базы данных."""
    print("[DATA SERVICE] Запрос get_all_complex_names...")
    mysql_session = None
    try:
        mysql_session = get_mysql_session()
        results = mysql_session.query(distinct(EstateHouse.complex_name)).order_by(EstateHouse.complex_name).all()
        complex_names = [row[0] for row in results]

        print(f"[DATA SERVICE] 📈 Найдено уникальных ЖК: {len(complex_names)}")
        mysql_session.close()
        return complex_names
    except Exception as e:
        print(f"[DATA SERVICE] ❌ ОШИБКА при запросе названий ЖК: {e}")
        if mysql_session:
            mysql_session.close()
        return []


def get_filter_options():
    """
    Получает уникальные значения для фильтров этажей и комнат.
    """
    print("[DATA SERVICE] Запрос get_filter_options...")
    mysql_session = None
    try:
        mysql_session = get_mysql_session()

        floors_q = mysql_session.query(distinct(EstateSell.estate_floor)).filter(
            EstateSell.estate_floor.isnot(None)
        )
        floors = sorted([f[0] for f in floors_q.all()])

        rooms_q = mysql_session.query(distinct(EstateSell.estate_rooms)).filter(
            EstateSell.estate_rooms.isnot(None)
        )
        rooms = sorted([r[0] for r in rooms_q.all()])

        print(f"[DATA SERVICE] ✔️ Найдено этажей: {len(floors)}, комнат: {len(rooms)}")
        mysql_session.close()
        return {'floors': floors, 'rooms': rooms}
    except Exception as e:
        print(f"[DATA SERVICE] ❌ ОШИБКА при запросе опций для фильтров: {e}")
        if mysql_session:
            mysql_session.close()
        return {'floors': [], 'rooms': []}
# app/core/report_exclusions.py
"""Исключения из настроек — во всех отчётах и в маркетинге.

В настройках задаются исключённые ЖК и исключённые квартиры. Раньше их
учитывали два места (подбор и сводка по остаткам), а каждый новый отчёт
приходилось не забыть научить. Здесь исключения применяются централизованно:
к каждому ORM-запросу внутри разделов отчётов и маркетинга добавляется
условие «кроме исключённого».

Почему не глобально на всё приложение: подбор, КП, скидки и сами настройки
должны видеть исключённые объекты — настройки, например, показывают их
списком, чтобы исключение можно было снять.

Что фильтруется:
* витрина Macro — дома, квартиры, сделки, поступления; заявки, звонки, лог
  статусов и встречи — по проекту заявки или встречи;
* локальные таблицы с привязкой к ЖК или квартире — планы продаж, реестры.

Чистый SQL (text) условие не получает — такие места нужно фильтровать явно.
"""

import logging

from flask import has_request_context, request
from sqlalchemy import and_, event, func, not_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, with_loader_criteria

logger = logging.getLogger(__name__)

# Разделы, где действуют исключения. Имена blueprint'ов.
REPORT_BLUEPRINTS = frozenset({
    'report', 'marketing', 'manager_analytics', 'obligations', 'registry',
    'cancellations', 'ai',
})

# Запрос с этой опцией исключения не получает — для служебных чтений.
SKIP_OPTION = 'skip_report_exclusions'
# Кэш живёт в окружении HTTP-запроса, а не в g: g принадлежит контексту
# приложения, и при вложенных контекстах исключения одного запроса достались
# бы другому.
_CACHE_KEY = 'finder.report_exclusions'


class _Exclusions:
    def __init__(self, complex_names, sell_ids, house_pks, house_keys, complex_ids):
        self.complex_names = sorted(complex_names)
        self.sell_ids = sorted(sell_ids)
        # estate_houses.id — на него ссылаются квартиры.
        self.house_pks = sorted(house_pks)
        # estate_houses.house_id и complex_id — на них ссылаются заявки и встречи.
        self.house_keys = sorted(house_keys)
        self.complex_ids = sorted(complex_ids)
        self.sells_in_complexes = None

    def __bool__(self):
        return bool(self.complex_names or self.sell_ids)


def exclusions_active():
    """Действуют ли исключения в текущем запросе."""
    if not has_request_context():
        return False
    return request.blueprint in REPORT_BLUEPRINTS


def _load(session):
    """Исключения читаются один раз на HTTP-запрос."""
    cached = request.environ.get(_CACHE_KEY)
    if cached is not None:
        return cached

    from app.core.extensions import db
    from app.models.estate_models import EstateHouse
    from app.models.exclusion_models import ExcludedComplex, ExcludedSell

    # Отдельные соединения, а не сессия запроса: ошибка здесь не должна
    # оставить сессию отчёта в сломанной транзакции, а Core-запросы не
    # проходят через обработчик и не зацикливаются.
    names, sell_ids = set(), set()
    try:
        with db.engine.connect() as conn:
            names = set(conn.scalars(select(ExcludedComplex.__table__.c.complex_name)).all())
            sell_ids = set(conn.scalars(select(ExcludedSell.__table__.c.sell_id)).all())
    except SQLAlchemyError as e:
        # Без таблицы исключений отчёт лучше показать полным, чем не показать.
        logger.warning('Исключения из настроек не прочитаны, отчёт строится без них: %s', e)

    house_pks, house_keys, complex_ids = set(), set(), set()
    if names:
        houses = EstateHouse.__table__
        with db.engines['mysql_source'].connect() as conn:
            rows = conn.execute(select(houses.c.id, houses.c.house_id, houses.c.complex_id)
                                .where(houses.c.complex_name.in_(names))).all()
        for pk, house_id, complex_id in rows:
            house_pks.add(pk)
            if house_id:
                house_keys.add(house_id)
            if complex_id:
                complex_ids.add(complex_id)

    exclusions = _Exclusions(names, sell_ids, house_pks, house_keys, complex_ids)
    request.environ[_CACHE_KEY] = exclusions
    return exclusions


def _sells_in_excluded_complexes(session, ex):
    """id квартир исключённых ЖК — для локальных таблиц, где подзапрос в
    MySQL невозможен (другая база)."""
    if ex.sells_in_complexes is None:
        from app.core.extensions import db
        from app.models.estate_models import EstateSell
        ex.sells_in_complexes = set()
        if ex.house_pks:
            sells = EstateSell.__table__
            with db.engines['mysql_source'].connect() as conn:
                ex.sells_in_complexes = set(conn.scalars(
                    select(sells.c.id).where(sells.c.house_id.in_(ex.house_pks))).all())
    return ex.sells_in_complexes


def _not_in(column, values, nullable=False):
    """NOT IN, который не теряет строки с NULL: NULL NOT IN (...) — это NULL,
    и WHERE выбросил бы строку, хотя исключать её не за что."""
    condition = column.notin_(values)
    return or_(column.is_(None), condition) if nullable else condition


def _lead_in_excluded_project(columns, ex):
    """Заявка относится к исключённому ЖК — по тем же правилам, что фильтр
    проекта в маркетинге: интерес к комплексу, дом интереса, дом сделки."""
    def value(col):
        return func.coalesce(col, 0)

    empty_complex = value(columns.first_complex_interest) == 0
    empty_house = value(columns.first_house_interest) == 0
    complex_ids = ex.complex_ids or [-1]
    house_keys = ex.house_keys or [-1]
    return or_(
        value(columns.first_complex_interest).in_(complex_ids),
        and_(empty_complex, value(columns.first_house_interest).in_(house_keys)),
        and_(empty_complex, empty_house, value(columns.house_id).in_(house_keys)),
    )


def _criteria(session, ex):
    from app.models.estate_models import EstateDeal, EstateHouse, EstateSell
    from app.models.finance_models import FinanceOperation
    from app.models.funnel_models import EstateBuy, EstateBuysStatusLog
    from app.models.marketing_models import Call, EstateMeeting
    from app.models.planning_models import SalesPlan
    from app.models.registry_models import CancellationRegistry, DealRegistry

    options = []

    def add(entity, condition):
        # propagate_to_loaders=False: ленивые связи (sell.house) грузятся как
        # есть — фильтруем выборки, а не ломаем уже полученные объекты.
        options.append(with_loader_criteria(entity, condition, include_aliases=True,
                                            propagate_to_loaders=False))

    sells_table = EstateSell.__table__
    buys_table = EstateBuy.__table__

    if ex.complex_names:
        add(EstateHouse, _not_in(EstateHouse.complex_name, ex.complex_names))
        add(SalesPlan, _not_in(SalesPlan.complex_name, ex.complex_names))
        add(CancellationRegistry, _not_in(CancellationRegistry.complex_name, ex.complex_names, nullable=True))

    sell_conditions = []
    if ex.sell_ids:
        sell_conditions.append(EstateSell.id.notin_(ex.sell_ids))
    if ex.house_pks:
        sell_conditions.append(EstateSell.house_id.notin_(ex.house_pks))
    if sell_conditions:
        add(EstateSell, and_(*sell_conditions))

        # Сделки и поступления — через квартиру. Подзапрос по таблице, а не по
        # модели: иначе он сам получил бы условие и перестал что-либо исключать.
        excluded_sells = select(sells_table.c.id).where(or_(
            sells_table.c.id.in_(ex.sell_ids or [-1]),
            sells_table.c.house_id.in_(ex.house_pks or [-1]),
        ))
        for entity in (EstateDeal, FinanceOperation):
            add(entity, entity.estate_sell_id.notin_(excluded_sells))

        # Реестры лежат в другой базе — подзапрос в MySQL из них не сделать.
        local_ids = sorted(set(ex.sell_ids) | _sells_in_excluded_complexes(session, ex))
        if local_ids:
            add(DealRegistry, DealRegistry.estate_sell_id.notin_(local_ids))
            add(CancellationRegistry, CancellationRegistry.estate_sell_id.notin_(local_ids))

    if ex.complex_names and (ex.complex_ids or ex.house_keys):
        add(EstateBuy, not_(_lead_in_excluded_project(EstateBuy, ex)))
        excluded_leads = select(buys_table.c.id).where(_lead_in_excluded_project(buys_table.c, ex))
        add(EstateBuysStatusLog, EstateBuysStatusLog.estate_buy_id.notin_(excluded_leads))
        add(Call, _not_in(Call.estate_id, excluded_leads, nullable=True))
        add(EstateMeeting, and_(
            _not_in(EstateMeeting.complex_id, ex.complex_ids or [-1], nullable=True),
            _not_in(EstateMeeting.house_id, ex.house_keys or [-1], nullable=True),
        ))

    return options


def _apply(state):
    if not state.is_select or state.execution_options.get(SKIP_OPTION):
        return
    if not exclusions_active():
        return
    ex = _load(state.session)
    if not ex:
        return
    options = _criteria(state.session, ex)
    if options:
        state.statement = state.statement.options(*options)


def init_report_exclusions(app):
    """Подключает обработчик один раз на процесс."""
    if not event.contains(Session, 'do_orm_execute', _apply):
        event.listen(Session, 'do_orm_execute', _apply)

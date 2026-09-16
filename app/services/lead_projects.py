# app/services/lead_projects.py
"""Проект заявки: как понять, к какому ЖК относится заявка.

В витрине у заявки три поля, связанных с проектом, и заполнены они на разных
этапах:

* first_complex_interest — комплекс первого интереса клиента;
* first_house_interest — дом первого интереса;
* house_id — дом объекта в сделке, появляется только с брони.

Раньше фильтр шёл только по house_id, и в проект попадали лишь заявки,
дошедшие до брони, — отсюда аномально мало заявок при выборе ЖК. Теперь
проект берётся по первому заполненному полю в порядке выше: маркетингу
важен интерес, с которым клиент пришёл.

Ключи тоже разные: поля заявки ведут в estate_houses.complex_id и
estate_houses.house_id, а не в estate_houses.id.
"""

from sqlalchemy import and_, or_

from ..core.db_utils import get_mysql_session
from app.models.estate_models import EstateHouse
from app.models.funnel_models import EstateBuy


def _empty(column):
    # Пустое значение витрина отдаёт то как NULL, то как 0.
    return or_(column.is_(None), column == 0)


def project_keys(complexes):
    """house_id и complex_id домов выбранных ЖК. None — фильтра нет."""
    if not complexes:
        return None
    rows = get_mysql_session().query(EstateHouse.house_id, EstateHouse.complex_id).filter(
        EstateHouse.complex_name.in_(complexes)).all()
    # Пустые списки подменяем на [-1]: ни один проект не подошёл, и показать
    # «всё, как без фильтра» было бы неправдой. Не 0 — нулём витрина помечает
    # незаполненное поле интереса, и такие заявки совпали бы с фильтром.
    house_ids = sorted({house_id for house_id, _ in rows if house_id}) or [-1]
    complex_ids = sorted({complex_id for _, complex_id in rows if complex_id}) or [-1]
    return house_ids, complex_ids


def lead_project_condition(complexes):
    """Условие на EstateBuy «заявка относится к выбранным ЖК». None — без фильтра."""
    keys = project_keys(complexes)
    if keys is None:
        return None
    house_ids, complex_ids = keys
    return or_(
        EstateBuy.first_complex_interest.in_(complex_ids),
        and_(_empty(EstateBuy.first_complex_interest),
             EstateBuy.first_house_interest.in_(house_ids)),
        and_(_empty(EstateBuy.first_complex_interest),
             _empty(EstateBuy.first_house_interest),
             EstateBuy.house_id.in_(house_ids)),
    )


def project_names_for(leads):
    """{id заявки: название ЖК} по тому же правилу, что и фильтр."""
    complex_ids = {lead.first_complex_interest for lead in leads if lead.first_complex_interest}
    house_ids = {value for lead in leads
                 for value in (lead.first_house_interest, lead.house_id) if value}
    if not complex_ids and not house_ids:
        return {}

    query = get_mysql_session().query(
        EstateHouse.house_id, EstateHouse.complex_id, EstateHouse.complex_name)
    conditions = []
    if complex_ids:
        conditions.append(EstateHouse.complex_id.in_(complex_ids))
    if house_ids:
        conditions.append(EstateHouse.house_id.in_(house_ids))
    by_complex, by_house = {}, {}
    for house_id, complex_id, name in query.filter(or_(*conditions)).all():
        if complex_id:
            by_complex.setdefault(complex_id, name)
        if house_id:
            by_house[house_id] = name

    names = {}
    for lead in leads:
        names[lead.id] = (by_complex.get(lead.first_complex_interest)
                          or by_house.get(lead.first_house_interest)
                          or by_house.get(lead.house_id))
    return names

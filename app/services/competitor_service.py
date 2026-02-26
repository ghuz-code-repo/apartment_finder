# app/services/competitor_service.py
import io
import os

import numpy as np
import pandas as pd
from flask import current_app
from werkzeug.utils import secure_filename

from app.core.extensions import db
from app.models.competitor_models import Competitor, CompetitorHistory  # Добавить импорт
from app.models.competitor_models import CompetitorMedia
from app.models.estate_models import EstateSell, EstateHouse, EstateDeal
from app.models.planning_models import (
    PropertyType, Discount, DiscountVersion, PaymentMethod,
    map_russian_to_mysql_key
)
from . import data_service, currency_service


def get_media_by_id(media_id):
    return CompetitorMedia.query.get(media_id)


def delete_media(media_id):
    media = CompetitorMedia.query.get(media_id)
    if media:
        # Формируем полный путь к файлу на диске
        full_path = os.path.join(current_app.static_folder, media.file_path)

        # Удаляем физический файл
        if os.path.exists(full_path):
            try:
                os.remove(full_path)
            except Exception as e:
                print(f"Ошибка при удалении файла с диска: {e}")

        # Удаляем запись из базы данных
        db.session.delete(media)
        db.session.commit()
        return True
    return False

def _get_our_project_dynamic_stats(complex_name, property_type_russian):
    """Рассчитывает динамические KPI наших ЖК из MySQL (Продажи, Остатки, Дно)."""
    mysql_key = map_russian_to_mysql_key(property_type_russian)
    house_ids = [h.id for h in EstateHouse.query.filter_by(complex_name=complex_name).all()]
    if not house_ids: return None

    # 1. Кол-во объектов и Продано
    total_units = EstateSell.query.filter(EstateSell.house_id.in_(house_ids),
                                          EstateSell.estate_sell_category == mysql_key).count()
    sold_count = EstateDeal.query.join(EstateSell).filter(
        EstateSell.house_id.in_(house_ids), EstateSell.estate_sell_category == mysql_key,
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).count()

    # 2. Остатки (Маркетинговый резерв и Подбор)
    remainders = EstateSell.query.filter(
        EstateSell.house_id.in_(house_ids), EstateSell.estate_sell_category == mysql_key,
        EstateSell.estate_sell_status_name.in_(["Маркетинговый резерв", "Подбор"]),
                                            EstateSell.estate_price > 0, EstateSell.estate_area > 0
    ).all()

    # 3. Скидки (МПП+РОП+КД) и Плановая дата кадастра
    active_version = DiscountVersion.query.filter_by(is_active=True).first()
    total_discount_rate, planned_date = 0, None
    if active_version:
        d = Discount.query.filter_by(
            version_id=active_version.id, complex_name=complex_name,
            property_type=PropertyType(property_type_russian), payment_method=PaymentMethod.FULL_PAYMENT
        ).first()
        if d:
            total_discount_rate = (d.mpp or 0) + (d.rop or 0) + (d.kd or 0)
            planned_date = d.cadastre_date

    # 4. Расчет средних величин (Цена остатка и Цена дна)
    avg_area, avg_price_sqm, avg_bottom_price = 0, 0, 0
    if remainders:
        usd_rate = currency_service.get_current_effective_rate() or 1.0
        deduction = 3_000_000 if property_type_russian == 'Квартира' else 0

        sum_area, sum_price_sqm_uzs, sum_bottom_sqm_uzs = 0, 0, 0
        for r in remainders:
            sum_area += r.estate_area
            sum_price_sqm_uzs += (r.estate_price / r.estate_area)
            # Цена дна: (Цена - Вычет) * (1 - Скидки)
            bottom_price = (r.estate_price - deduction) * (1 - total_discount_rate)
            sum_bottom_sqm_uzs += (bottom_price / r.estate_area)

        avg_area = sum_area / len(remainders)
        avg_price_sqm = (sum_price_sqm_uzs / len(remainders)) / usd_rate
        avg_bottom_price = (sum_bottom_sqm_uzs / len(remainders)) / usd_rate

    return {
        'total_units': total_units, 'sold_count': sold_count, 'avg_area': avg_area,
        'avg_price_sqm': avg_price_sqm, 'avg_bottom_price': avg_bottom_price,
        'planned_date': planned_date
    }


def export_our_projects():
    """Экспорт наших ЖК: ручные поля из SQLite."""
    cols = ['Наименование ЖК', 'Тип', 'Широта', 'Долгота', 'Класс', 'Высота потолков',
            'Благоустройство', 'Стадия строительства', 'Первоначальная дата кадастра']
    data = []
    for name in data_service.get_all_complex_names():
        for pt in PropertyType:
            saved = Competitor.query.filter_by(name=name, property_type=pt.value, is_internal=True).first()
            data.append({
                'Наименование ЖК': name, 'Тип': pt.value,
                'Широта': saved.lat if saved else None, 'Долгота': saved.lng if saved else None,
                'Класс': saved.property_class if saved else None,
                'Высота потолков': saved.ceiling_height if saved else None,
                'Благоустройство': saved.amenities if saved else None,
                'Стадия строительства': saved.construction_stage if saved else None,
                'Первоначальная дата кадастра': saved.initial_cadastre_date if saved else None
            })
    return _to_excel(data, cols, "OurProjects")


def import_our_projects(file):
    """Импорт наших ЖК: сохранение ручных полей + авто-расчет системных из MySQL."""
    df = pd.read_excel(file).replace({np.nan: None, pd.NaT: None})
    for _, row in df.dropna(subset=['Наименование ЖК']).iterrows():
        name, p_type = str(row['Наименование ЖК']).strip(), str(row['Тип']).strip()
        stats = _get_our_project_dynamic_stats(name, p_type)

        comp = Competitor.query.filter_by(name=name, property_type=p_type, is_internal=True).first() or Competitor(
            is_internal=True)
        comp.name, comp.property_type = name, p_type
        # Ручные поля из Excel
        comp.lat, comp.lng = row.get('Широта'), row.get('Долгота')
        comp.property_class, comp.ceiling_height = row.get('Класс'), row.get('Высота потолков')
        comp.amenities, comp.construction_stage = row.get('Благоустройство'), row.get('Стадия строительства')
        comp.initial_cadastre_date = pd.to_datetime(row.get('Первоначальная дата кадастра')).date() if row.get(
            'Первоначальная дата кадастра') else None
        # Системные поля (всегда перезаписываются из MySQL)
        if stats:
            comp.units_count, comp.sold_count = stats['total_units'], stats['sold_count']
            comp.avg_area, comp.avg_price_sqm = stats['avg_area'], stats['avg_price_sqm']
            comp.avg_bottom_price, comp.planned_cadastre_date = stats['avg_bottom_price'], stats['planned_date']
        db.session.add(comp)
    db.session.commit()


def export_competitors():
    """Экспорт внешних конкурентов: все поля из SQLite."""
    cols = ['Наименование ЖК', 'Тип', 'Широта', 'Долгота', 'Класс', 'Высота потолков', 'Благоустройство',
            'Стадия строительства', 'Кол-во объектов', 'Продано шт', 'Средняя площадь',
            'Средняя цена за квадратный метр остатка', 'Средняя стоимость дна остатков',
            'Плановая Дата кадастр', 'Первоначальная дата кадастра', 'Прямой конкурент для']
    data = []
    for c in Competitor.query.filter_by(is_internal=False).all():
        data.append({
            'Наименование ЖК': c.name, 'Тип': c.property_type, 'Широта': c.lat, 'Долгота': c.lng,
            'Класс': c.property_class, 'Высота потолков': c.ceiling_height, 'Благоустройство': c.amenities,
            'Стадия строительства': c.construction_stage, 'Кол-во объектов': c.units_count,
            'Продано шт': c.sold_count, 'Средняя площадь': c.avg_area,
            'Средняя цена за квадратный метр остатка': c.avg_price_sqm,
            'Средняя стоимость дна остатков': c.avg_bottom_price,
            'Плановая Дата кадастр': c.planned_cadastre_date,
            'Первоначальная дата кадастра': c.initial_cadastre_date,
            'Прямой конкурент для': c.direct_competitor_name
        })
    return _to_excel(data, cols, "Competitors")


def import_competitors(file):
    """Импорт внешних конкурентов: все данные берутся из Excel."""
    df = pd.read_excel(file).replace({np.nan: None, pd.NaT: None})
    for _, row in df.dropna(subset=['Наименование ЖК']).iterrows():
        name, p_type = str(row['Наименование ЖК']).strip(), str(row['Тип']).strip()
        comp = Competitor.query.filter_by(name=name, property_type=p_type, is_internal=False).first() or Competitor(
            is_internal=False)
        comp.name, comp.property_type = name, p_type
        comp.lat, comp.lng = row.get('Широта'), row.get('Долгота')
        comp.property_class, comp.ceiling_height = row.get('Класс'), row.get('Высота потолков')
        comp.amenities, comp.construction_stage = row.get('Благоустройство'), row.get('Стадия строительства')
        comp.units_count, comp.sold_count = row.get('Кол-во объектов'), row.get('Продано шт')
        comp.avg_area, comp.avg_price_sqm = row.get('Средняя площадь'), row.get(
            'Средняя цена за квадратный метр остатка')
        comp.avg_bottom_price = row.get('Средняя стоимость дна остатков')
        comp.direct_competitor_name = row.get('Прямой конкурент для')
        for d_col, attr in [('Плановая Дата кадастр', 'planned_cadastre_date'),
                            ('Первоначальная дата кадастра', 'initial_cadastre_date')]:
            val = row.get(d_col)
            setattr(comp, attr, pd.to_datetime(val).date() if val else None)
        db.session.add(comp)
        db.session.flush()
        record_history(comp)
    db.session.commit()


def get_comparison(comp_id, our_complex_name):
    """
    Сравнение: теперь фокусируемся только на Цене Дна.
    Блокируем сравнение с самим собой.
    """
    competitor = Competitor.query.get(comp_id)

    # Защита от сравнения с самим собой
    if not competitor or competitor.name.strip().lower() == our_complex_name.strip().lower():
        return None

    # Получаем динамику (stats) и ручные данные (our_saved)
    stats = _get_our_project_dynamic_stats(our_complex_name, 'Квартира')
    our_saved = Competitor.query.filter_by(
        name=our_complex_name,
        property_type='Квартира',
        is_internal=True
    ).first()

    return {
        'competitor': competitor,
        'our_project': {
            'name': our_complex_name,
            # Оставляем только цену дна
            'avg_bottom_price': stats['avg_bottom_price'] if stats else 0,
            'units': stats['total_units'] if stats else 0,
            'sold': stats['sold_count'] if stats else 0,
            'avg_area': stats['avg_area'] if stats else 0,
            'property_class': our_saved.property_class if our_saved else '-',
            'construction_stage': our_saved.construction_stage if our_saved else '-'
        }
    }


def get_competitor_by_id(comp_id):
    return Competitor.query.get_or_404(comp_id)


def update_competitor_info(comp_id, data):
    comp = Competitor.query.get(comp_id)
    if comp:
        comp.description = data.get('description')
        comp.property_class = data.get('property_class')
        comp.ceiling_height = data.get('ceiling_height')
        comp.amenities = data.get('amenities')
        db.session.commit()
    return comp


def save_media(comp_id, file):
    filename = secure_filename(file.filename)
    upload_path = os.path.join(current_app.static_folder, 'uploads', 'competitors', str(comp_id))
    os.makedirs(upload_path, exist_ok=True)

    file_path = os.path.join(upload_path, filename)
    file.save(file_path)

    # Сохранение в БД (путь относительно static)
    relative_path = f'uploads/competitors/{comp_id}/{filename}'

    ext = filename.rsplit('.', 1)[1].lower()
    media_type = 'image' if ext in ['jpg', 'jpeg', 'png', 'webp'] else 'document'

    media = CompetitorMedia(
        competitor_id=comp_id,
        file_path=relative_path,
        media_type=media_type
    )
    db.session.add(media)
    db.session.commit()
def record_history(competitor):
    """Вспомогательная функция для создания записи в истории."""
    history_entry = CompetitorHistory(
        competitor_id=competitor.id,
        avg_price_sqm=competitor.avg_price_sqm,
        avg_bottom_price=competitor.avg_bottom_price,
        units_count=competitor.units_count,
        sold_count=competitor.sold_count
    )
    db.session.add(history_entry)

# В функциях import_our_projects и import_competitors
# после db.session.add(comp) и коммита (или перед ним) вызываем запись:




def get_market_dynamics_data():
    """Возвращает историю изменений цен для всех конкурентов."""
    history = CompetitorHistory.query.join(Competitor).order_by(CompetitorHistory.recorded_at.asc()).all()

    # Группировка данных для графиков (например, по ЖК)
    data = {}
    for entry in history:
        name = entry.competitor.name
        if name not in data:
            data[name] = {'labels': [], 'prices': []}
        data[name]['labels'].append(entry.recorded_at.strftime('%d.%m.%Y'))
        data[name]['prices'].append(entry.avg_price_sqm or 0)
    return data
def _to_excel(data, columns, sheet):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as w:
        pd.DataFrame(data, columns=columns).to_excel(w, index=False, sheet_name=sheet)
    out.seek(0)
    return out
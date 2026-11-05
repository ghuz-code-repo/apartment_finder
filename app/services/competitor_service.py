# app/services/competitor_service.py
import io
import math
import os
import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from flask import current_app
from werkzeug.utils import secure_filename

from app.core.extensions import db
from app.core.media import media_dir, resolve_media_path
from app.models.competitor_models import Competitor, CompetitorHistory  # Добавить импорт
from app.models.competitor_models import CompetitorMedia
from app.models.estate_models import EstateSell, EstateHouse, EstateDeal
from app.models.planning_models import (
    PropertyType, Discount, DiscountVersion, PaymentMethod,
    map_russian_to_mysql_key
)
from . import data_service, currency_service


_SPACES = ('\xa0', ' ', ' ', ' ')
_NUMBER_RE = re.compile(r'[-+]?\d+(?:\.\d+)?')


def _to_float(value):
    """Приводит значение из Excel/БД к числу, мусор -> None.

    '41,33' -> 41.33, '1 500,5' -> 1500.5, '1,250.75' -> 1250.75,
    '1500 $' / '3,2 м' -> число без единиц. Если в тексте несколько чисел
    ('2025-01-12', '3-4'), угадывать не берёмся — None.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        num = float(value)
        return None if math.isnan(num) or math.isinf(num) else num
    text = str(value)
    for ch in _SPACES + (' ',):
        text = text.replace(ch, '')
    if not text:
        return None
    if ',' in text and '.' in text:
        # Разделитель тысяч — тот, что встречается раньше: '1.250,75' / '1,250.75'.
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    else:
        text = text.replace(',', '.')
    numbers = _NUMBER_RE.findall(text)
    return float(numbers[0]) if len(numbers) == 1 else None


def _to_int(value):
    num = _to_float(value)
    return int(round(num)) if num is not None else None


def _to_str(value):
    """Текстовые поля: числа из Excel не должны попадать в БД как float."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value)
    for ch in _SPACES:
        text = text.replace(ch, ' ')
    text = ' '.join(text.split())
    return text or None


def _to_date(value):
    """Дата из ячейки Excel: дата, число-серийник Excel или текст '22.03.2026'.

    Текст читаем как день.месяц.год — так пишут даты у нас. Без dayfirst
    '03.04.2026' превращалось в 4 марта вместо 3 апреля.
    """
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return None if pd.isna(value) else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        num = float(value)
        # Ячейка не в формате даты: Excel хранит число дней от 1899-12-30.
        if math.isnan(num) or not (20000 < num < 80000):
            return None
        return (datetime(1899, 12, 30) + timedelta(days=num)).date()
    text = _to_str(value)
    if not text:
        return None
    iso = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?', text)
    try:
        if iso:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        parsed = pd.to_datetime(text, dayfirst=True)
    except (ValueError, OverflowError):
        return None
    return None if pd.isna(parsed) else parsed.date()


def build_map_markers(competitors):
    """Готовит безопасные данные для карты.

    Координаты приводятся к числам: одна испорченная запись (например, '41,33'
    из Excel) не должна ломать весь JS-блок на странице карты.
    """
    markers = []
    for c in competitors:
        lat, lng = _to_float(c.lat), _to_float(c.lng)
        if lat is None or lng is None:
            continue
        markers.append({
            'id': c.id,
            'name': c.name or '',
            'lat': lat,
            'lng': lng,
            'class': c.property_class or '',
            'type': c.property_type or '',
            'isInternal': bool(c.is_internal),
            'directComp': c.direct_competitor_name or '',
        })
    return markers


def get_media_by_id(media_id):
    return CompetitorMedia.query.get(media_id)


def delete_media(media_id):
    media = CompetitorMedia.query.get(media_id)
    if media:
        # Путь считаем от UPLOAD_ROOT, а не от static: медиа переехали из
        # static, и склейка со static_folder указывала в пустоту — запись из
        # БД удалялась, а файл молча оставался на диске.
        full_path = resolve_media_path(media.file_path)

        # Удаляем физический файл
        if full_path and os.path.exists(full_path):
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


OUR_COLUMNS = ['Наименование ЖК', 'Тип', 'Широта', 'Долгота', 'Класс', 'Высота потолков',
               'Благоустройство', 'Стадия строительства', 'Первоначальная дата кадастра']
COMPETITOR_COLUMNS = ['Наименование ЖК', 'Тип', 'Широта', 'Долгота', 'Класс', 'Высота потолков',
                      'Благоустройство', 'Стадия строительства', 'Кол-во объектов', 'Продано шт',
                      'Средняя площадь', 'Средняя цена за квадратный метр остатка',
                      'Средняя стоимость дна остатков', 'Плановая Дата кадастр',
                      'Первоначальная дата кадастра', 'Прямой конкурент для']

# Листы общего файла. Старые названия тоже узнаём: файлы, скачанные раньше
# раздельными кнопками, должны загружаться без переименования листов.
OUR_SHEET = 'Наши ЖК'
COMPETITOR_SHEET = 'Конкуренты'
_OUR_SHEET_NAMES = {OUR_SHEET.lower(), 'ourprojects'}
_COMPETITOR_SHEET_NAMES = {COMPETITOR_SHEET.lower(), 'competitors'}
# Колонки, которые есть только у конкурентов: по ним узнаём лист с чужим названием.
_COMPETITOR_ONLY_COLUMNS = set(COMPETITOR_COLUMNS) - set(OUR_COLUMNS)

NAME_COL, TYPE_COL = 'Наименование ЖК', 'Тип'

# Колонка Excel -> (атрибут модели, парсер). Порядок — как в выгрузке.
_FIELD_SPECS = {
    'Широта': ('lat', _to_float),
    'Долгота': ('lng', _to_float),
    'Класс': ('property_class', _to_str),
    'Высота потолков': ('ceiling_height', _to_float),
    'Благоустройство': ('amenities', _to_str),
    'Стадия строительства': ('construction_stage', _to_str),
    'Кол-во объектов': ('units_count', _to_int),
    'Продано шт': ('sold_count', _to_int),
    'Средняя площадь': ('avg_area', _to_float),
    'Средняя цена за квадратный метр остатка': ('avg_price_sqm', _to_float),
    'Средняя стоимость дна остатков': ('avg_bottom_price', _to_float),
    'Плановая Дата кадастр': ('planned_cadastre_date', _to_date),
    'Первоначальная дата кадастра': ('initial_cadastre_date', _to_date),
    'Прямой конкурент для': ('direct_competitor_name', _to_str),
}
# У наших ЖК из файла берутся только ручные поля, аналитика считается из MySQL.
_OUR_FIELDS = [c for c in OUR_COLUMNS if c in _FIELD_SPECS]
_COMPETITOR_FIELDS = [c for c in COMPETITOR_COLUMNS if c in _FIELD_SPECS]

# Как ещё люди подписывают те же колонки. Сравнение идёт по нормализованному
# виду (регистр, ё/е, пробелы и знаки препинания не важны), поэтому сюда
# пишем только действительно другие формулировки.
_COLUMN_ALIASES = {
    'Наименование ЖК': ['Название ЖК', 'ЖК', 'Наименование', 'Название', 'Проект', 'Name'],
    'Тип': ['Тип недвижимости', 'Тип объекта', 'Тип помещения', 'Type'],
    'Широта': ['Lat', 'Latitude'],
    'Долгота': ['Lng', 'Lon', 'Long', 'Longitude'],
    'Класс': ['Класс ЖК', 'Класс жилья', 'Class'],
    'Высота потолков': ['Высота потолков м', 'Потолки', 'Потолки м'],
    'Стадия строительства': ['Стадия', 'Этап строительства'],
    'Кол-во объектов': ['Количество объектов', 'Всего объектов', 'Кол-во квартир',
                        'Количество квартир', 'Объектов'],
    'Продано шт': ['Продано', 'Продано объектов', 'Кол-во проданных', 'Количество проданных'],
    'Средняя площадь': ['Средняя площадь м2', 'Средняя площадь остатка', 'Ср площадь'],
    'Средняя цена за квадратный метр остатка': [
        'Средняя цена за м2 остатка', 'Средняя цена м2 остатка', 'Средняя цена за м2',
        'Средняя цена м2', 'Цена за м2', 'Цена м2', 'Средняя цена за кв м остатка',
        'Средняя цена за квадратный метр'],
    'Средняя стоимость дна остатков': ['Средняя стоимость дна', 'Стоимость дна', 'Цена дна',
                                       'Средняя цена дна', 'Дно'],
    'Плановая Дата кадастр': ['Плановая дата кадастра', 'Плановая дата', 'Плановый кадастр'],
    'Первоначальная дата кадастра': ['Первоначальная дата', 'Изначальная дата кадастра',
                                     'Первоначальный кадастр'],
    'Прямой конкурент для': ['Прямой конкурент', 'Конкурент для', 'Прямой конкурент нашего ЖК'],
}

_TYPE_ALIASES = {
    'квартира': 'Квартира', 'квартиры': 'Квартира', 'жилье': 'Квартира', 'flat': 'Квартира',
    'коммерческое помещение': 'Коммерческое помещение', 'коммерция': 'Коммерческое помещение',
    'коммерческие помещения': 'Коммерческое помещение', 'comm': 'Коммерческое помещение',
    'парковка': 'Парковка', 'парковки': 'Парковка', 'паркинг': 'Парковка', 'garage': 'Парковка',
    'кладовое помещение': 'Кладовое помещение', 'кладовка': 'Кладовое помещение',
    'кладовки': 'Кладовое помещение', 'кладовые помещения': 'Кладовое помещение',
    'storageroom': 'Кладовое помещение',
}
DEFAULT_TYPE = PropertyType.FLAT.value

# Предупреждений бывает сотни (например, весь столбец в непонятном формате),
# пользователю хватит первых — дальше только счётчик.
MAX_WARNINGS = 30


def _norm(text):
    """Ключ для сравнения заголовков и названий: регистр, ё, пробелы, знаки не важны."""
    text = (_to_str(text) or '').lower().replace('ё', 'е').replace('²', '2')
    return ' '.join(re.sub(r'[^\w]+', ' ', text).split())


_HEADER_LOOKUP = {}
for _canon, _aliases in _COLUMN_ALIASES.items():
    for _variant in [_canon, *_aliases]:
        _HEADER_LOOKUP.setdefault(_norm(_variant), _canon)
for _canon in set(COMPETITOR_COLUMNS) | set(OUR_COLUMNS):
    _HEADER_LOOKUP.setdefault(_norm(_canon), _canon)


def _name_key(value):
    """Ключ ЖК: 'Abu\\xa0Dhabi' и 'abu  dhabi' — один и тот же проект."""
    return ' '.join((_to_str(value) or '').lower().replace('ё', 'е').split())


def _clean_type(value):
    text = _to_str(value)
    if not text:
        return DEFAULT_TYPE
    return _TYPE_ALIASES.get(_norm(text), text)


class _Report:
    """Что загрузили и что не смогли — для сообщения пользователю."""

    def __init__(self):
        self.count = 0
        self.warnings = []
        self.extra = 0

    def warn(self, text):
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(text)
        else:
            self.extra += 1

    def messages(self):
        msgs = list(self.warnings)
        if self.extra:
            msgs.append(f'…и ещё {self.extra} замечаний')
        return msgs


def _prepare_sheet(raw, sheet_name, report):
    """Сырой лист (header=None) -> таблица с каноническими названиями колонок.

    Строку заголовков ищем среди первых 15: над таблицей бывает шапка или
    пустые строки. Возвращает None, если таблицы на листе нет.
    """
    raw = raw.dropna(how='all').dropna(axis=1, how='all')
    if raw.empty:
        return None
    header_pos = None
    for pos in range(min(15, len(raw))):
        cells = {_HEADER_LOOKUP.get(_norm(v)) for v in raw.iloc[pos].tolist()}
        if NAME_COL in cells:
            header_pos = pos
            break
    if header_pos is None:
        return None

    columns, seen = [], set()
    for col_idx, title in zip(raw.columns, raw.iloc[header_pos].tolist()):
        canon = _HEADER_LOOKUP.get(_norm(title))
        title_text = _to_str(title)
        if canon is None:
            if title_text:
                report.warn(f'Лист «{sheet_name}»: колонка «{title_text}» не распознана и пропущена')
            columns.append(None)
        elif canon in seen:
            report.warn(f'Лист «{sheet_name}»: колонка «{title_text}» повторяет «{canon}» — взята первая')
            columns.append(None)
        else:
            seen.add(canon)
            columns.append(canon)

    body = raw.iloc[header_pos + 1:]
    df = pd.DataFrame(
        {canon: body[col_idx].tolist() for col_idx, canon in zip(raw.columns, columns) if canon},
        index=body.index,
    )
    # Индекс сырого листа — номер строки с нуля: +1 даёт номер строки в Excel.
    return df.astype(object).where(pd.notna(df), None)


def _read_sheets(file):
    """Все листы книги: {имя: сырой DataFrame без заголовка}."""
    return pd.read_excel(file, sheet_name=None, header=None)


def _apply_fields(comp, row, fields, present, sheet, excel_row, report, fill_only=False):
    """Записывает в объект только колонки, которые есть в файле.

    Раньше отсутствующая (или подписанная чуть иначе) колонка давала None
    и молча стирала это поле у всех ЖК. Пустая ячейка в существующей
    колонке по-прежнему очищает значение — так поле правят вручную.
    fill_only — для повторной строки того же ЖК в файле: она дополняет
    и обновляет первую, но пустыми ячейками её не стирает.
    """
    for column in fields:
        if column not in present:
            continue
        attr, parse = _FIELD_SPECS[column]
        raw = row.get(column)
        value = parse(raw)
        if value is None and _to_str(raw):
            report.warn(f'Лист «{sheet}», строка {excel_row}, «{column}»: '
                        f'не удалось прочитать «{_to_str(raw)}» — поле оставлено пустым')
        if value is None and fill_only:
            continue
        setattr(comp, attr, value)


def _iter_rows(df, sheet, report):
    """Строки с названием ЖК; номера строк — как в Excel."""
    for idx, row in df.iterrows():
        excel_row = int(idx) + 1
        name = _to_str(row.get(NAME_COL))
        if not name:
            if any(v is not None for v in row.tolist()):
                report.warn(f'Лист «{sheet}», строка {excel_row}: нет названия ЖК — строка пропущена')
            continue
        yield excel_row, name, row


class _Existing:
    """Записи из базы по ключу «название + тип» без учёта регистра и пробелов.

    Раньше ЖК искали по точному названию, и 'GOROD' / 'Gorod' или
    'Abu\\xa0Dhabi' / 'Abu Dhabi' заводились отдельными записями — на карте
    две отметки в одной точке. Такие дубли объединяем, как только ЖК
    встречается в загружаемом файле: фото, документы и история цен
    переезжают на оставшуюся (самую старую) запись.
    """

    def __init__(self, is_internal, report):
        self.items, self.dupes, self.report = {}, {}, report
        for c in Competitor.query.filter_by(is_internal=is_internal).order_by(Competitor.id).all():
            key = (_name_key(c.name), _name_key(c.property_type))
            if key in self.items:
                self.dupes.setdefault(key, []).append(c)
            else:
                self.items[key] = c

    def get(self, key, name):
        comp = self.items.get(key)
        extras = self.dupes.pop(key, [])
        if comp is not None and extras:
            _merge_into(comp, extras)
            self.report.warn(f'«{name}»: в базе было записей одного ЖК — {len(extras) + 1}, '
                             f'объединены в одну (фото и история цен сохранены)')
        return comp

    def add(self, key, comp):
        self.items[key] = comp


def _merge_into(keep, extras):
    for dup in extras:
        for media in list(dup.media):
            keep.media.append(media)
        CompetitorHistory.query.filter_by(competitor_id=dup.id).update(
            {'competitor_id': keep.id}, synchronize_session=False)
        if not keep.description and dup.description:
            keep.description = dup.description
        db.session.delete(dup)
    db.session.flush()


def export_our_projects():
    """Экспорт наших ЖК: ручные поля из SQLite."""
    return _to_excel(_our_rows(), OUR_COLUMNS, "OurProjects")


def _our_rows():
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
    return data


def _import_single(file, importer):
    """Загрузка файла одной части (наши ЖК или конкуренты): берём первый
    лист, на котором нашлась таблица."""
    report = _Report()
    try:
        for sheet_name, raw in _read_sheets(file).items():
            df = _prepare_sheet(raw, sheet_name, report)
            if df is not None:
                importer(df, str(sheet_name), report)
                break
        else:
            report.warn('В файле не найдена таблица с колонкой «Наименование ЖК»')
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return report


def import_our_projects(file):
    """Импорт наших ЖК: сохранение ручных полей + авто-расчет системных из MySQL."""
    return _import_single(file, _import_our_rows)


def _import_our_rows(df, sheet, report):
    present = set(df.columns)
    existing = _Existing(is_internal=True, report=report)
    known_types = {pt.value for pt in PropertyType}
    for excel_row, name, row in _iter_rows(df, sheet, report):
        p_type = _clean_type(row.get(TYPE_COL))
        if p_type not in known_types:
            report.warn(f'Лист «{sheet}», строка {excel_row}: неизвестный тип «{p_type}» — строка пропущена')
            continue
        key = (_name_key(name), _name_key(p_type))
        comp = existing.get(key, name)
        if comp is None:
            comp = Competitor(is_internal=True)
            existing.add(key, comp)
        comp.name, comp.property_type = name, p_type
        _apply_fields(comp, row, _OUR_FIELDS, present, sheet, excel_row, report)
        # Системные поля (всегда перезаписываются из MySQL)
        stats = _get_our_project_dynamic_stats(name, p_type)
        if stats:
            comp.units_count, comp.sold_count = stats['total_units'], stats['sold_count']
            comp.avg_area, comp.avg_price_sqm = stats['avg_area'], stats['avg_price_sqm']
            comp.avg_bottom_price, comp.planned_cadastre_date = stats['avg_bottom_price'], stats['planned_date']
        db.session.add(comp)
        report.count += 1


def export_competitors():
    """Экспорт внешних конкурентов: все поля из SQLite."""
    return _to_excel(_competitor_rows(), COMPETITOR_COLUMNS, "Competitors")


def _competitor_rows():
    data = []
    for c in Competitor.query.filter_by(is_internal=False).order_by(Competitor.name).all():
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
    return data


def import_competitors(file):
    """Импорт внешних конкурентов: все данные берутся из Excel."""
    return _import_single(file, _import_competitor_rows)


_HISTORY_FIELDS = ('avg_price_sqm', 'avg_bottom_price', 'units_count', 'sold_count')


def _import_competitor_rows(df, sheet, report):
    present = set(df.columns)
    existing = _Existing(is_internal=False, report=report)
    seen, touched = {}, {}
    for excel_row, name, row in _iter_rows(df, sheet, report):
        p_type = _clean_type(row.get(TYPE_COL))
        key = (_name_key(name), _name_key(p_type))
        repeat = key in seen
        if repeat:
            report.warn(f'Лист «{sheet}», строка {excel_row}: «{name}» ({p_type}) уже был в строке '
                        f'{seen[key]} — строки объединены, при расхождении взято значение из строки {excel_row}')
        seen[key] = excel_row

        comp = existing.get(key, name)
        if comp is None:
            comp = Competitor(is_internal=False)
            existing.add(key, comp)
            touched[key] = (comp, None)
        elif not repeat:
            touched[key] = (comp, tuple(getattr(comp, f) for f in _HISTORY_FIELDS))
        comp.name, comp.property_type = name, p_type
        _apply_fields(comp, row, _COMPETITOR_FIELDS, present, sheet, excel_row, report,
                      fill_only=repeat)
        db.session.add(comp)
        if not repeat:
            report.count += 1

    db.session.flush()
    # Одна точка истории на ЖК за загрузку, и только если цифры сдвинулись:
    # повторная загрузка того же файла не плодит одинаковые точки на графике.
    for comp, before in touched.values():
        if before is None or before != tuple(getattr(comp, f) for f in _HISTORY_FIELDS):
            record_history(comp)


def export_all(include_our=True, include_competitors=True):
    """Один файл на все проекты карты: наши ЖК и конкуренты на отдельных листах.

    Колонки у листов разные — у наших ЖК аналитика считается из MySQL и в
    файл не выгружается, — поэтому в одну таблицу их не сводим. Лист, на
    который у пользователя нет права, в файл не попадает.
    """
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
        if include_our:
            pd.DataFrame(_our_rows(), columns=OUR_COLUMNS).to_excel(
                writer, index=False, sheet_name=OUR_SHEET)
        if include_competitors:
            pd.DataFrame(_competitor_rows(), columns=COMPETITOR_COLUMNS).to_excel(
                writer, index=False, sheet_name=COMPETITOR_SHEET)
    out.seek(0)
    return out


def _sheet_kind(sheet_name, df):
    name = str(sheet_name).strip().lower()
    if name in _OUR_SHEET_NAMES:
        return 'our'
    if name in _COMPETITOR_SHEET_NAMES:
        return 'competitors'
    if NAME_COL not in df.columns:
        return None
    return 'competitors' if _COMPETITOR_ONLY_COLUMNS & set(df.columns) else 'our'


def import_all(file, allow_our=True, allow_competitors=True):
    """Загружает общий файл: каждый лист уходит в свой импорт.

    Возвращает, сколько строк загружено по каждому виду, какие листы
    пропущены (нет права или лист не похож ни на один из шаблонов) и
    замечания по ячейкам, которые не удалось прочитать.
    Всё в одной транзакции: ошибка на втором листе не оставит первый
    загруженным наполовину.
    """
    sheets = _read_sheets(file)
    result = {'our': 0, 'competitors': 0, 'skipped': [], 'warnings': []}
    our_report, comp_report = _Report(), _Report()
    try:
        for sheet_name, raw in sheets.items():
            sheet = str(sheet_name)
            probe = _Report()
            df = _prepare_sheet(raw, sheet, probe)
            kind = _sheet_kind(sheet, df) if df is not None else None
            if kind == 'our' and allow_our:
                our_report.warnings += probe.warnings
                _import_our_rows(df, sheet, our_report)
            elif kind == 'competitors' and allow_competitors:
                comp_report.warnings += probe.warnings
                _import_competitor_rows(df, sheet, comp_report)
            else:
                result['skipped'].append(sheet)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    result['our'], result['competitors'] = our_report.count, comp_report.count
    result['warnings'] = our_report.messages() + comp_report.messages()
    return result


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
            'avg_price_sqm': stats['avg_price_sqm'] if stats else 0,
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
    """Ручная правка из карточки ЖК.

    Значения формы — строки: без приведения в Float-колонку SQLite попадала
    строка ('' или '3,2'), и потом ломались карта и выгрузка.
    Меняем только поля, которые пришли в форме.
    """
    comp = Competitor.query.get(comp_id)
    if comp:
        for field, parse in (('description', _to_str), ('property_class', _to_str),
                             ('ceiling_height', _to_float), ('amenities', _to_str),
                             ('construction_stage', _to_str)):
            if field in data:
                setattr(comp, field, parse(data.get(field)))
        db.session.commit()
    return comp


def save_media(comp_id, file):
    filename = secure_filename(file.filename)
    upload_path = media_dir('competitors', str(comp_id))

    file_path = os.path.join(upload_path, filename)
    file.save(file_path)

    # Сохранение в БД (путь относительно UPLOAD_ROOT)
    relative_path = f'competitors/{comp_id}/{filename}'

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
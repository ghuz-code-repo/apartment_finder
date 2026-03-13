import os
import hashlib
import json
from sqlalchemy import create_engine, Table, MetaData
from sqlalchemy.orm import sessionmaker
from flask import current_app
from datetime import datetime

from ..core.extensions import db
from .discount_service import process_discounts_from_excel
from ..models.auth_models import SalesManager
from ..models import planning_models, system_models
from ..models.estate_models import EstateHouse, EstateSell, EstateDeal
from ..models.finance_models import FinanceOperation
from ..models.funnel_models import EstateBuy, EstateBuysStatusLog

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..', '..'))
DISCOUNTS_EXCEL_PATH = os.path.join(PROJECT_ROOT, 'data_sources', 'discounts_template.xlsx')


def _calculate_row_hash(data_dict):
    """Вычисляет хеш SHA-256 для словаря данных."""
    encoded_row = json.dumps(data_dict, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(encoded_row).hexdigest()


def _sync_table(mysql_session, source_table_name, local_model, columns_map):
    """Универсальная функция для синхронизации одной таблицы с использованием хеширования."""
    print(f"[SYNC] ⚙️  Начало синхронизации таблицы '{source_table_name}'...")
    meta = MetaData()
    source_table = Table(source_table_name, meta, autoload_with=mysql_session.bind)
    source_query = mysql_session.query(source_table)
    if source_table_name == 'estate_houses':
        print("[SYNC] -> Применяю фильтр для 'estate_houses': `complex_name` не должен быть NULL.")
        source_query = source_query.filter(source_table.c.complex_name.isnot(None))
    source_records_map = {row.id: row for row in source_query}
    source_ids = set(source_records_map.keys())
    print(f"[SYNC] -> Загружено {len(source_ids)} записей из MySQL (после фильтрации).")
    local_hashes = dict(db.session.query(local_model.id, local_model.data_hash).all())
    local_ids = set(local_hashes.keys())
    print(f"[SYNC] -> Найдено {len(local_ids)} записей в локальной базе.")
    ids_to_add = source_ids - local_ids
    ids_to_delete = local_ids - source_ids
    ids_to_check = source_ids.intersection(local_ids)
    updates_count = 0
    for item_id in ids_to_add:
        row = source_records_map[item_id]
        data_for_model = {model_col: getattr(row, source_col) for model_col, source_col in columns_map.items()}
        data_for_hash = {model_col: getattr(row, source_col) for model_col, source_col in columns_map.items() if
                         model_col != 'id'}
        data_for_model['id'] = item_id
        data_for_model['data_hash'] = _calculate_row_hash(data_for_hash)
        db.session.add(local_model(**data_for_model))
    for item_id in ids_to_check:
        row = source_records_map[item_id]
        data_for_hash = {model_col: getattr(row, source_col) for model_col, source_col in columns_map.items() if
                         model_col != 'id'}
        new_hash = _calculate_row_hash(data_for_hash)
        if new_hash != local_hashes[item_id]:
            instance = db.session.get(local_model, item_id)
            if instance:
                data_for_model = {model_col: getattr(row, source_col) for model_col, source_col in columns_map.items()}
                for key, value in data_for_model.items():
                    setattr(instance, key, value)
                instance.data_hash = new_hash
                updates_count += 1
    if ids_to_delete:
        db.session.query(local_model).filter(local_model.id.in_(ids_to_delete)).delete(synchronize_session=False)
    db.session.commit()
    print(f"[SYNC] ✅  Синхронизация '{source_table_name}' завершена. "
          f"Добавлено: {len(ids_to_add)}, Обновлено: {updates_count}, Удалено: {len(ids_to_delete)}.")


def _sync_managers(mysql_session):
    """Специальная функция для синхронизации менеджеров, обрабатывающая дубликаты по имени."""
    source_table_name = 'users'
    local_model = SalesManager
    print(f"[SYNC-MGR] ⚙️  Начало специальной синхронизации таблицы '{source_table_name}'...")
    meta = MetaData()
    source_table = Table(source_table_name, meta, autoload_with=mysql_session.bind)
    source_records = {}
    for row in mysql_session.query(source_table).order_by(source_table.c.id):
        name = getattr(row, 'users_name', "").strip()
        if name and name not in source_records:
            source_records[name] = row
    source_names = set(source_records.keys())
    print(f"[SYNC-MGR] -> Загружено {len(source_names)} уникальных менеджеров из MySQL.")
    local_records = {mgr.full_name: mgr for mgr in db.session.query(local_model).all()}
    local_names = set(local_records.keys())
    print(f"[SYNC-MGR] -> Найдено {len(local_names)} менеджеров в локальной базе.")
    names_to_add = source_names - local_names
    names_to_delete = local_names - source_names
    names_to_check = source_names.intersection(local_names)
    updates_count = 0
    for name in names_to_add:
        row = source_records[name]
        data_for_hash = {'full_name': name, 'post_title': getattr(row, 'post_title', None)}
        new_mgr = local_model(
            id=row.id,
            full_name=name,
            post_title=getattr(row, 'post_title', None),
            data_hash=_calculate_row_hash(data_for_hash)
        )
        db.session.add(new_mgr)
    for name in names_to_check:
        source_row = source_records[name]
        local_mgr = local_records[name]
        data_for_hash = {'full_name': name, 'post_title': getattr(source_row, 'post_title', None)}
        new_hash = _calculate_row_hash(data_for_hash)
        if new_hash != local_mgr.data_hash:
            local_mgr.post_title = getattr(source_row, 'post_title', None)
            local_mgr.data_hash = new_hash
            updates_count += 1
    if names_to_delete:
        for name in names_to_delete:
            db.session.delete(local_records[name])
    db.session.commit()
    print(f"[SYNC-MGR] ✅  Синхронизация '{source_table_name}' завершена. "
          f"Добавлено: {len(names_to_add)}, Обновлено: {updates_count}, Удалено: {len(names_to_delete)}.")


def incremental_update_from_mysql():
    """Выполняет инкрементное обновление данных из MySQL на основе хешей."""
    print(f"\n[HASH UPDATE] 🔄 НАЧАЛО ОБНОВЛЕНИЯ ПО ХЕШАМ ({datetime.now()})...")
    try:
        mysql_uri = current_app.config['SOURCE_MYSQL_URI']
        mysql_engine = create_engine(mysql_uri)
        MySQLSession = sessionmaker(bind=mysql_engine)
        mysql_session = MySQLSession()

        # Вызовы для всех таблиц
        _sync_table(mysql_session, 'estate_houses', EstateHouse,
                    {'complex_name': 'complex_name', 'name': 'name', 'geo_house': 'geo_house'})

        # <<< ИЗМЕНЕНИЕ: Вызываем специальную функцию для estate_sells >>>
        _sync_sells(mysql_session)

        _sync_table(mysql_session, 'estate_buys', EstateBuy,
                    {'date_added': 'date_added', 'created_at': 'created_at', 'status_name': 'status_name',
                     'custom_status_name': 'custom_status_name'})
        _sync_table(mysql_session, 'estate_buys_statuses_log', EstateBuysStatusLog,
                    {'log_date': 'log_date', 'estate_buy_id': 'estate_buy_id', 'status_to_name': 'status_to_name',
                     'status_custom_to_name': 'status_custom_to_name', 'manager_id': 'users_id'})
        _sync_table(mysql_session, 'estate_deals', EstateDeal,
                    {'estate_sell_id': 'estate_sell_id', 'deal_status_name': 'deal_status_name',
                     'deal_manager_id': 'deal_manager_id', 'agreement_date': 'agreement_date',
                     'preliminary_date': 'preliminary_date', 'deal_sum': 'deal_sum', 'date_modified': 'date_modified'})
        _sync_table(mysql_session, 'finances', FinanceOperation,
                    {'estate_sell_id': 'estate_sell_id', 'summa': 'summa', 'status_name': 'status_name',
                     'payment_type': 'types_name', 'date_added': 'date_added', 'date_to': 'date_to',
                     'manager_id': 'respons_manager_id'})
        _sync_managers(mysql_session)

        print("[HASH UPDATE] ✅ ОБНОВЛЕНИЕ ПО ХЕШАМ ЗАВЕРШЕНО.\n")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"[HASH UPDATE] ❌ ОШИБКА ПРИ ОБНОВЛЕНИИ ПО ХЕШАМ: {e}")
        return False
    finally:
        if 'mysql_session' in locals() and mysql_session.is_active:
            mysql_session.close()


def _sync_sells(mysql_session):
    """
    Специальная функция для синхронизации estate_sells, которая выполняет
    трансформацию поля estate_sell_category.
    """
    source_table_name = 'estate_sells'
    local_model = EstateSell
    columns_map = {
        'house_id': 'house_id', 'estate_sell_category': 'estate_sell_category',
        'estate_floor': 'estate_floor', 'estate_rooms': 'estate_rooms',
        'estate_price_m2': 'estate_price_m2', 'estate_sell_status_name': 'estate_sell_status_name',
        'estate_price': 'estate_price', 'estate_area': 'estate_area'
    }
    # Словарь для маппинга, как в оригинальном коде
    CATEGORY_MAPPING = {
        'flat': 'Квартира', 'comm': 'Коммерческое помещение',
        'garage': 'Парковка', 'storageroom': 'Кладовое помещение'
    }

    print(f"[SYNC-SELLS] ⚙️  Начало специальной синхронизации таблицы '{source_table_name}'...")

    meta = MetaData()
    source_table = Table(source_table_name, meta, autoload_with=mysql_session.bind)
    source_query = mysql_session.query(source_table)
    source_records_map = {row.id: row for row in source_query}
    source_ids = set(source_records_map.keys())
    print(f"[SYNC-SELLS] -> Загружено {len(source_ids)} записей из MySQL.")

    local_hashes = dict(db.session.query(local_model.id, local_model.data_hash).all())
    local_ids = set(local_hashes.keys())
    print(f"[SYNC-SELLS] -> Найдено {len(local_ids)} записей в локальной базе.")

    ids_to_add = source_ids - local_ids
    ids_to_delete = local_ids - source_ids
    ids_to_check = source_ids.intersection(local_ids)
    updates_count = 0

    def get_mapped_data(row):
        """Возвращает словарь с данными для модели, применяя маппинг категорий."""
        data = {}
        for model_col, source_col in columns_map.items():
            value = getattr(row, source_col)
            if model_col == 'estate_sell_category':
                # Применяем трансформацию!
                value = CATEGORY_MAPPING.get(value, value)
            data[model_col] = value
        return data

    for item_id in ids_to_add:
        row = source_records_map[item_id]
        data_for_model = get_mapped_data(row)
        data_for_model['id'] = item_id
        data_for_model['data_hash'] = _calculate_row_hash(data_for_model)
        db.session.add(local_model(**data_for_model))

    for item_id in ids_to_check:
        row = source_records_map[item_id]
        data_for_model = get_mapped_data(row)
        new_hash = _calculate_row_hash(data_for_model)
        if new_hash != local_hashes[item_id]:
            instance = db.session.get(local_model, item_id)
            if instance:
                for key, value in data_for_model.items():
                    setattr(instance, key, value)
                instance.data_hash = new_hash
                updates_count += 1

    if ids_to_delete:
        db.session.query(local_model).filter(local_model.id.in_(ids_to_delete)).delete(synchronize_session=False)

    db.session.commit()
    print(f"[SYNC-SELLS] ✅  Синхронизация '{source_table_name}' завершена. "
          f"Добавлено: {len(ids_to_add)}, Обновлено: {updates_count}, Удалено: {len(ids_to_delete)}.")
# <<< ВОЗВРАЩЕННАЯ ФУНКЦИЯ >>>

def refresh_estate_data_from_mysql():
    """
    Выполняет ПОЛНУЮ очистку и последующую синхронизацию.
    Используется для первоначальной настройки.
    """
    print("\n[FULL REFRESH] 🔄 НАЧАЛО ПОЛНОЙ ОЧИСТКИ И СИНХРОНИЗАЦИИ...")

    # Сначала очищаем таблицы в правильном порядке (дочерние -> родительские)
    print("[FULL REFRESH] 🧹 Очистка существующих данных...")
    db.session.query(FinanceOperation).delete()
    db.session.query(EstateDeal).delete()
    db.session.query(EstateBuysStatusLog).delete()
    db.session.query(EstateSell).delete()
    db.session.query(EstateHouse).delete()
    db.session.query(EstateBuy).delete()
    db.session.query(SalesManager).delete()
    db.session.commit()
    print("[FULL REFRESH] ✔️ Данные очищены.")

    # Затем запускаем обычную инкрементную синхронизацию,
    # которая в данном случае заполнит пустые таблицы.
    return incremental_update_from_mysql()
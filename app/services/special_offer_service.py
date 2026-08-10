# app/services/special_offer_service.py

import os
from werkzeug.utils import secure_filename
from PIL import Image
from flask import current_app, url_for
from app.models import planning_models
from ..core.db_utils import get_planning_session, get_mysql_session
from app.models.special_offer_models import MonthlySpecial
from app.models.estate_models import EstateSell, EstateHouse
from datetime import date

RESERVATION_FEE = 3_000_000
# --- Константы для загрузки изображений ---
UPLOAD_FOLDER = 'uploads/floor_plans'  # Путь внутри 'static'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'svg'}
MAX_IMAGE_WIDTH = 1200  # Максимальная ширина изображения в пикселях


def _allowed_file(filename):
    """Проверяет, имеет ли файл разрешенное расширение."""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _optimize_and_save_image(image_file_storage):
    """Оптимизирует и сохраняет изображение, возвращает имя файла."""
    if not image_file_storage or not _allowed_file(image_file_storage.filename):
        raise ValueError("Недопустимый формат файла. Разрешены: png, jpg, jpeg, svg.")

    filename = secure_filename(image_file_storage.filename)
    # Создаем уникальное имя файла, чтобы избежать перезаписи
    unique_filename = f"{os.path.splitext(filename)[0]}_{int(date.today().strftime('%Y%m%d%H%M%S'))}.webp"

    upload_path = os.path.join(current_app.static_folder, UPLOAD_FOLDER)
    os.makedirs(upload_path, exist_ok=True)

    full_path = os.path.join(upload_path, unique_filename)

    # Обработка изображения
    img = Image.open(image_file_storage)

    # Конвертируем в RGB для совместимости с WebP
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Изменяем размер, если изображение слишком большое
    if img.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / float(img.width)
        new_height = int(float(img.height) * float(ratio))
        img = img.resize((MAX_IMAGE_WIDTH, new_height), Image.LANCZOS)

    # Сохраняем в формате WebP для лучшей производительности
    img.save(full_path, 'WEBP', quality=85)

    return unique_filename


def add_special_offer(sell_id, usp_text, extra_discount, image_file):
    planning_session = get_planning_session()
    """Добавляет новое специальное предложение."""
    if planning_session.query(MonthlySpecial).filter_by(sell_id=sell_id).first():
        raise ValueError(f"Специальное предложение для квартиры с ID {sell_id} уже существует.")

    # Оптимизируем и сохраняем изображение
    saved_filename = _optimize_and_save_image(image_file)

    new_special = MonthlySpecial(
        sell_id=sell_id,
        usp_text=usp_text,
        extra_discount=extra_discount,
        floor_plan_image_filename=saved_filename,
        expires_at=MonthlySpecial.set_initial_expiry()  # Устанавливаем срок до конца текущего месяца
    )
    planning_session.add(new_special)  # <--- ИЗМЕНЕНО
    planning_session.commit()
    return new_special


def get_active_special_offers():
    """Возвращает список активных спец. предложений с ПОЛНЫМ расчетом цены. (ИСПРАВЛЕННАЯ ВЕРСИЯ)"""
    today = date.today()

    # --- Получаем все стандартные скидки для 100% оплаты ---
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО

    # --- Получаем все стандартные скидки для 100% оплаты ---
    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
    if not active_version:
        return []  # Если нет системы скидок, нет и расчета

    discounts_map = {
        (d.complex_name, d.property_type): d
        for d in active_version.discounts
        if d.payment_method == planning_models.PaymentMethod.FULL_PAYMENT
    }

    # --- Шаг 1: Получаем все активные спецпредложения из 'planning.db' ---
    active_specials = planning_session.query(MonthlySpecial).filter(
        MonthlySpecial.is_active == True,
        MonthlySpecial.expires_at >= today
    ).order_by(MonthlySpecial.created_at.desc()).all()

    if not active_specials:
        return []

    specials_map = {s.sell_id: s for s in active_specials}
    sell_ids = list(specials_map.keys())

    # --- Шаг 2: Получаем квартиры из основной базы ---
    sells_data = mysql_session.query(
        EstateSell, EstateHouse
    ).join(
        EstateHouse, EstateSell.house_id == EstateHouse.id
    ).filter(
        EstateSell.id.in_(sell_ids)
    ).all()

    # --- Шаг 3: Совмещаем данные и ДЕЛАЕМ ПОЛНЫЙ РАСЧЕТ ---
    offers_list = []
    for sell, house in sells_data:
        special = specials_map.get(sell.id)
        if not special or not sell.estate_price or sell.estate_price <= RESERVATION_FEE:
            continue

        # Находим стандартную скидку
        prop_type_enum = planning_models.PropertyType(sell.estate_sell_category)
        standard_discount_obj = discounts_map.get((house.complex_name, prop_type_enum))

        standard_discount_rate = 0
        if standard_discount_obj:
            standard_discount_rate = (standard_discount_obj.mpp or 0) + (standard_discount_obj.rop or 0) + (
                        standard_discount_obj.action or 0)

        # Суммируем скидки
        special_discount_rate = (special.extra_discount or 0) / 100.0
        total_discount_rate = standard_discount_rate + special_discount_rate

        # Рассчитываем итоговую цену
        price_for_calc = sell.estate_price - RESERVATION_FEE
        final_price = price_for_calc * (1 - total_discount_rate)

        offers_list.append({
            'sell_id': sell.id,
            'usp_text': special.usp_text,
            'image_url': url_for('static', filename=f'{UPLOAD_FOLDER}/{special.floor_plan_image_filename}'),
            'complex_name': house.complex_name,
            'house_name': house.name,
            'rooms': sell.estate_rooms,
            'area': sell.estate_area,
            'price': sell.estate_price,
            'final_price': final_price,  # <-- Новая итоговая цена
            'total_discount_percent': total_discount_rate * 100  # <-- Новая общая скидка
        })

    final_sorted_list = sorted(offers_list, key=lambda x: specials_map[x['sell_id']].created_at, reverse=True)
    return final_sorted_list


def get_special_offer_details_by_sell_id(sell_id: int):
    """Находит спец. предложение по ID КВАРТИРЫ (sell_id)."""
    # Эта функция ищет по sell_id, как и было нужно для публичной страницы
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    special = planning_session.query(MonthlySpecial).filter_by(sell_id=sell_id).first()  # <--- ИЗМЕНЕНО
    if not special:
        return None

    # Чтобы не дублировать код, мы просто вызываем другую функцию, передавая ей правильный ID
    return get_special_offer_details_by_special_id(special.id)

def get_special_offer_details_by_special_id(special_id: int):
    """Возвращает полную информацию по одному спец. предложению ПО ЕГО ID. (ИСПРАВЛЕННАЯ ВЕРСИЯ)"""

    # --- Шаг 1: Находим спецпредложение по его собственному ID в 'planning.db' ---
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    mysql_session = get_mysql_session()
    special = planning_session.query(MonthlySpecial).get(special_id)
    if not special:
        return None

    # Теперь, когда у нас есть 'special', мы можем использовать его sell_id для второго запроса
    sell_id = special.sell_id

    # --- Получаем стандартные скидки ---
    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(is_active=True).first()
    if not active_version:
        return None

    discounts_map = {
        (d.complex_name, d.property_type): d
        for d in active_version.discounts
        if d.payment_method == planning_models.PaymentMethod.FULL_PAYMENT
    }

    # --- Шаг 2: Получаем детали квартиры из основной базы ---
    sell_data = mysql_session.query(EstateSell, EstateHouse).join(EstateHouse,
                                                               EstateSell.house_id == EstateHouse.id).filter(
        EstateSell.id == sell_id).first()
    if not sell_data:
        return None

    sell, house = sell_data

    # --- Шаг 3: Совмещаем данные и делаем полный расчет ---
    if not sell.estate_price or sell.estate_price <= RESERVATION_FEE:
        return None

    prop_type_enum = planning_models.PropertyType(sell.estate_sell_category)
    standard_discount_obj = discounts_map.get((house.complex_name, prop_type_enum))

    standard_discount_rate = 0
    if standard_discount_obj:
        standard_discount_rate = (standard_discount_obj.mpp or 0) + (standard_discount_obj.rop or 0) + (
                    standard_discount_obj.action or 0)

    special_discount_rate = (special.extra_discount or 0) / 100.0
    total_discount_rate = standard_discount_rate + special_discount_rate

    price_for_calc = sell.estate_price - RESERVATION_FEE
    final_price = price_for_calc * (1 - total_discount_rate)

    # ... (возвращаем тот же словарь, что и раньше)
    return {
        'special_id': special.id,
        'sell_id': sell.id,
        'usp_text': special.usp_text,
        'image_url': url_for('static', filename=f'{UPLOAD_FOLDER}/{special.floor_plan_image_filename}'),
        'extra_discount': special.extra_discount,
        'expires_at': special.expires_at.isoformat(),
        'is_active': special.is_active,
        'complex_name': house.complex_name,
        'house_name': house.name,
        'rooms': sell.estate_rooms,
        'floor': sell.estate_floor,
        'area': sell.estate_area,
        'price': sell.estate_price,
        'final_price': final_price,
        'total_discount_percent': total_discount_rate * 100,
        'standard_discount_percent': standard_discount_rate * 100,
        'reservation_fee': RESERVATION_FEE
    }

def get_all_special_offers():
    """Возвращает ВСЕ спец. предложения для панели администратора. (ИСПРАВЛЕННАЯ ВЕРСИЯ)"""
    # Шаг 1: Получаем ВСЕ спецпредложения из 'planning.db'
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО

    # Шаг 1: Получаем ВСЕ спецпредложения из 'planning.db'
    all_specials_from_db = planning_session.query(MonthlySpecial).order_by(MonthlySpecial.created_at.desc()).all()

    if not all_specials_from_db:
        return []

    # Создаем карту для удобного сопоставления и получаем список ID
    specials_map = {s.sell_id: s for s in all_specials_from_db}
    sell_ids = list(specials_map.keys())

    # Шаг 2: Получаем детали для этих квартир из основной базы
    sells_data = mysql_session.query(
        EstateSell, EstateHouse
    ).join(
        EstateHouse, EstateSell.house_id == EstateHouse.id
    ).filter(
        EstateSell.id.in_(sell_ids)
    ).all()

    # Создаем карту квартир для быстрого доступа
    sells_map = {s.id: (s, h) for s, h in sells_data}

    # Шаг 3: Совмещаем данные, сохраняя порядок изначального запроса
    # (проходимся по all_specials_from_db, а не по результату второго запроса)
    offers_list = []
    for special in all_specials_from_db:
        if special.sell_id in sells_map:
            sell, house = sells_map[special.sell_id]
            offers_list.append({
                'special_id': special.id,
                'sell_id': sell.id,
                'usp_text': special.usp_text,
                'extra_discount': special.extra_discount,
                'expires_at': special.expires_at.isoformat(),
                'is_active': special.is_active,
                'complex_name': house.complex_name,
                'house_name': house.name,
            })

    return offers_list


def update_special_offer(special_id, usp_text, extra_discount, image_file=None):
    """Обновляет существующее специальное предложение."""
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    special_to_update = planning_session.query(MonthlySpecial).get_or_404(special_id)

    special_to_update.usp_text = usp_text
    special_to_update.extra_discount = extra_discount

    # Если загружен новый файл, заменяем старый
    if image_file and image_file.filename != '':
        # Удаляем старый файл изображения, чтобы не копить мусор
        old_image_path = os.path.join(current_app.static_folder, UPLOAD_FOLDER,
                                      special_to_update.floor_plan_image_filename)
        if os.path.exists(old_image_path):
            os.remove(old_image_path)

        # Сохраняем новый и обновляем имя файла в базе
        saved_filename = _optimize_and_save_image(image_file)
        special_to_update.floor_plan_image_filename = saved_filename

    planning_session.commit()
    return special_to_update


def delete_special_offer(special_id):
    """Удаляет специальное предложение и его изображение."""
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    special_to_delete = planning_session.query(MonthlySpecial).get_or_404(special_id)  # <--- ИЗМЕНЕНО

    # Удаляем файл изображения с сервера
    image_path = os.path.join(current_app.static_folder, UPLOAD_FOLDER, special_to_delete.floor_plan_image_filename)
    if os.path.exists(image_path):
        os.remove(image_path)

    # Удаляем запись из базы данных
    planning_session.delete(special_to_delete)  # <--- ИЗМЕНЕНО
    planning_session.commit()


def extend_special_offer(special_id: int):
    """Продлевает срок действия предложения."""
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    special = planning_session.query(MonthlySpecial).get_or_404(special_id)  # <--- ИЗМЕНЕНО
    special.extend_offer()
    planning_session.commit()  # <--- ИЗМЕНЕНО
    return special

# Тут можно добавить функции update_special_offer и delete_special_offer по аналогии
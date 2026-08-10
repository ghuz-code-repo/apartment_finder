import os
import sys
from sqlalchemy import text
from app import create_app
from app.core.extensions import db


def run_migration():
    app = create_app()
    with app.app_context():
        engine = db.engine

        with engine.begin() as connection:
            # Отключение внешних ключей на время миграции
            connection.execute(text("PRAGMA foreign_keys=OFF"))

            # 1. Создание временной таблицы с корректной схемой (без UNIQUE на estate_sell_id)
            connection.execute(text("""
                CREATE TABLE cancellation_registry_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    estate_sell_id INTEGER NOT NULL,
                    created_at DATETIME,
                    comment VARCHAR(255),
                    complex_name VARCHAR(255),
                    house_name VARCHAR(255),
                    entrance VARCHAR(50),
                    number VARCHAR(50),
                    cat_type VARCHAR(100),
                    floor VARCHAR(50),
                    rooms VARCHAR(50),
                    area FLOAT,
                    is_free BOOLEAN DEFAULT 0,
                    is_no_money BOOLEAN DEFAULT 0,
                    is_change_object BOOLEAN DEFAULT 0,
                    contract_number VARCHAR(100),
                    contract_date DATE,
                    contract_sum FLOAT,
                    manual_number VARCHAR(64),
                    manual_date DATE,
                    manual_sum FLOAT
                )
            """))

            # 2. Перенос существующих данных во временную таблицу
            # Поля соответствуют модели CancellationRegistry
            connection.execute(text("""
                INSERT INTO cancellation_registry_new (
                    id, estate_sell_id, created_at, comment, complex_name, house_name, 
                    entrance, number, cat_type, floor, rooms, area, is_free, 
                    is_no_money, is_change_object, contract_number, contract_date, 
                    contract_sum, manual_number, manual_date, manual_sum
                )
                SELECT 
                    id, estate_sell_id, created_at, comment, complex_name, house_name, 
                    entrance, number, cat_type, floor, rooms, area, is_free, 
                    is_no_money, is_change_object, contract_number, contract_date, 
                    contract_sum, manual_number, manual_date, manual_sum
                FROM cancellation_registry
            """))

            # 3. Удаление старой таблицы с ограничением UNIQUE
            connection.execute(text("DROP TABLE cancellation_registry"))

            # 4. Переименование новой таблицы в оригинальное название
            connection.execute(text("ALTER TABLE cancellation_registry_new RENAME TO cancellation_registry"))

            # 5. Создание не уникального индекса для estate_sell_id
            connection.execute(
                text("CREATE INDEX ix_cancellation_registry_estate_sell_id ON cancellation_registry (estate_sell_id)"))

            connection.execute(text("PRAGMA foreign_keys=ON"))

        print("Миграция завершена успешно.")


if __name__ == "__main__":
    run_migration()
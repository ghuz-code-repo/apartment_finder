"""Ручной запуск ремонта схемы main_app.db.

То же самое приложение делает само на старте (см. app/core/schema_repair.py),
скрипт нужен, когда базу надо починить, не поднимая сервис.

Прежняя версия безусловно пересоздавала cancellation_registry через
DROP TABLE и падала на уже починенной базе. Теперь вся логика — в общей
идемпотентной функции.
"""
import os
import sys

sys.path.append(os.getcwd())

from app import create_app
from app.core.extensions import db
from app.core.schema_repair import repair_cancellation_registry


def run_migration():
    app = create_app()
    with app.app_context():
        print(f"База: {db.engine.url}")
        if repair_cancellation_registry(db.engine):
            print("Миграция завершена: UNIQUE с cancellation_registry.estate_sell_id снят.")
        else:
            print("Схема уже актуальна, менять нечего.")


if __name__ == "__main__":
    run_migration()

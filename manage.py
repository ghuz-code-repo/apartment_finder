# migrate_and_fill_rates.py
from app import create_app
from app.core.extensions import db
from app.services.currency_service import sync_historical_rates
from sqlalchemy import text


def run_migration():
    app = create_app()
    with app.app_context():
        print("1. Проверка структуры базы данных...")

        # Создаем новые таблицы (DailyCurrencyRate)
        db.create_all()

        # Добавляем колонку use_historical_rate в существующую таблицу
        # Используем try/except на случай, если колонка уже есть
        try:
            db.session.execute(text(
                "ALTER TABLE currency_settings ADD COLUMN use_historical_rate BOOLEAN DEFAULT 0 NOT NULL"
            ))
            db.session.commit()
            print("Колонка 'use_historical_rate' успешно добавлена.")
        except Exception as e:
            db.session.rollback()
            if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                print("Колонка 'use_historical_rate' уже существует.")
            else:
                print(f"Предупреждение при миграции: {e}")

        print("\n2. Начало наполнения историческими данными...")
        sync_historical_rates(2020)
        print("\nГотово! База данных подготовлена и наполнена.")


if __name__ == "__main__":
    run_migration()
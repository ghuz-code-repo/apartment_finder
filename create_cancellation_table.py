import os
import sys

# Добавляем текущую директорию в путь, чтобы Python видел папку 'app'
sys.path.append(os.getcwd())

from app import create_app
from app.core.extensions import db

# ВАЖНО: Импортируем модель, чтобы SQLAlchemy знала о её существовании перед созданием
try:
    from app.models.registry_models import CancellationRegistry

    print("Модель CancellationRegistry успешно импортирована.")
except ImportError as e:
    print(f"ОШИБКА: Не удалось импортировать модель. Проверьте файл app/models/registry_models.py.\nДетали: {e}")
    sys.exit(1)


def init_db():
    app = create_app()
    with app.app_context():
        print(f"Подключение к БД: {app.config.get('SQLALCHEMY_DATABASE_URI')}")

        # db.create_all() создаст таблицу только если её еще нет.
        # Существующие данные не пострадают.
        try:
            db.create_all()
            print("-" * 50)
            print("УСПЕШНО: Таблица 'cancellation_registry' создана (или уже существовала).")
            print("-" * 50)
        except Exception as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА при создании таблицы: {e}")


if __name__ == "__main__":
    init_db()
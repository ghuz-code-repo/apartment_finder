import os
from app import create_app
from app.core.config import DevelopmentConfig
from app.services.initial_load_service import refresh_estate_data_from_mysql, incremental_update_from_mysql
from app.core.extensions import db
from prefix_middleware import PrefixMiddleware

# Создаем приложение Flask
app = create_app(DevelopmentConfig)

# Apply prefix middleware for running behind gateway at /finder
app.wsgi_app = PrefixMiddleware(app.wsgi_app, app=app, prefix='/finder')

# Путь к файлу-флагу
LOCK_FILE_PATH = os.path.join(app.instance_path, 'update.lock')


def setup_database():
    """
    Создает все таблицы во всех сконфигурированных базах данных.
    Локальные пользователи/роли больше не создаются — авторизация через gateway.
    """
    with app.app_context():
        print("\n--- [ОТЛАДКА] Начало функции setup_database ---")

        from app.models import (auth_models, planning_models, estate_models,
                                finance_models, exclusion_models, funnel_models,
                        special_offer_models)

        print("--- [ОТЛАДКА] Вызов единого db.create_all() для всех баз... ---")
        db.create_all()
        print("--- [ОТЛАДКА] db.create_all() для всех баз завершен. ---")
        print("--- [ОТЛАДКА] Функция setup_database завершена. ---\n")


# Этот блок выполняется только один раз при запуске сервера
if os.environ.get('WERKZEUG_RUN_MAIN') is None:
    # ШАГ 1: Инициализация баз данных
    setup_database()

    # ШАГ 2: Обновление данных из MySQL, используя флаг блокировки
    try:
        with open(LOCK_FILE_PATH, 'w') as f:
            f.write('locked')
        print(f"[UPDATE FLAG] Файл блокировки создан: {LOCK_FILE_PATH}")
        with app.app_context():
            incremental_update_from_mysql()
    finally:
        if os.path.exists(LOCK_FILE_PATH):
            os.remove(LOCK_FILE_PATH)
            print(f"[UPDATE FLAG] Файл блокировки удален.")


if __name__ == '__main__':
    print("[FLASK APP] 🚦 Запуск веб-сервера Flask...")
    app.run(host='0.0.0.0', port=5000, debug=True)
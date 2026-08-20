import os
from app import create_app
from app.core.config import DevelopmentConfig
from app.core.extensions import db
from app.core.schema_repair import repair_schema
from prefix_middleware import PrefixMiddleware

# Создаем приложение Flask
app = create_app(DevelopmentConfig)

# Apply prefix middleware for running behind gateway at /finder
app.wsgi_app = PrefixMiddleware(app.wsgi_app, app=app, prefix='/finder')


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
        # create_all() существующие таблицы не меняет, поэтому базы, созданные
        # до правок моделей, чинятся отдельно.
        repair_schema(db)
        print("--- [ОТЛАДКА] Функция setup_database завершена. ---\n")


# Этот блок выполняется только один раз при запуске сервера.
# Обновления из MySQL здесь нет: модели estate_*/finance_* читают источник
# напрямую через bind 'mysql_source', зеркалить их некуда.
if os.environ.get('WERKZEUG_RUN_MAIN') is None:
    setup_database()


if __name__ == '__main__':
    print("[FLASK APP] 🚦 Запуск веб-сервера Flask...")
    app.run(host='0.0.0.0', port=5000, debug=True)
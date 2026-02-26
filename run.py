import os
from app import create_app
from app.core.config import DevelopmentConfig
from app.services.initial_load_service import refresh_estate_data_from_mysql, incremental_update_from_mysql
from app.core.extensions import db
from app.models import auth_models
from prefix_middleware import PrefixMiddleware

# Создаем приложение Flask
app = create_app(DevelopmentConfig)

# Apply prefix middleware for running behind gateway at /finder
app.wsgi_app = PrefixMiddleware(app.wsgi_app, app=app, prefix='/finder')

# Путь к файлу-флагу
LOCK_FILE_PATH = os.path.join(app.instance_path, 'update.lock')


def setup_database():
    """
    Создает все таблицы во всех сконфигурированных базах данных,
    а также начальные роли и пользователя 'admin'.
    """
    with app.app_context():
        print("\n--- [ОТЛАДКА] Начало функции setup_database ---")

        # Импортируем все модули с моделями, чтобы SQLAlchemy о них знала
        from app.models import (auth_models, planning_models, estate_models,
                                finance_models, exclusion_models, funnel_models,
                        special_offer_models)

        # Используем один вызов db.create_all(), который создаст таблицы
        # в основной базе и во всех базах, указанных вSQLALCHEMY_BINDS.
        print("--- [ОТЛАДКА] Вызов единого db.create_all() для всех баз... ---")
        db.create_all()
        print("--- [ОТЛАДКА] db.create_all() для всех баз завершен. ---")

        # Код создания ролей и админа остается без изменений
        print("--- [ОТЛАДКА] Проверка существования ролей... ---")
        if auth_models.Role.query.count() == 0:
            print("--- [ОТЛАДКА] Ролей не найдено. Создание начальных ролей и прав... ---")

            permissions_map = {
                'view_selection': 'Просмотр системы подбора',
                'view_discounts': 'Просмотр активной системы скидок',
                'view_version_history': 'Просмотр истории версий скидок',
                'view_plan_fact_report': 'Просмотр План-факт отчета',
                'view_inventory_report': 'Просмотр отчета по остаткам',
                'view_manager_report': 'Просмотр отчетов по менеджерам',
                'view_project_dashboard': 'Просмотр аналитики по проектам',
                'manage_discounts': 'Управление версиями скидок (создание, активация)',
                'manage_settings': 'Управление настройками (калькуляторы, курс)',
                'manage_users': 'Управление пользователями',
                'upload_data': 'Загрузка данных (планы и т.д.)',
                'download_kpi_report': 'Выгрузка ведомости по KPI менеджеров',
                'manage_specials': 'Управление специальными предложениями (акции)'
            }

            roles_permissions = {
                'MPP': ['view_selection', 'view_discounts'],
                'MANAGER': [
                    'view_selection', 'view_discounts', 'view_version_history', 'manage_settings',
                    'view_plan_fact_report', 'view_inventory_report', 'view_manager_report', 'view_project_dashboard'
                ],
                'ADMIN': [
                    'view_selection', 'view_discounts', 'view_version_history', 'manage_discounts',
                    'manage_settings', 'manage_users', 'upload_data',
                    'view_plan_fact_report', 'view_inventory_report', 'view_manager_report', 'view_project_dashboard',
                    'manage_specials','download_kpi_report'
                ]
            }

            all_permissions = {}
            for name, desc in permissions_map.items():
                p = auth_models.Permission(name=name, description=desc)
                all_permissions[name] = p
                db.session.add(p)

            for role_name, permissions_list in roles_permissions.items():
                role = auth_models.Role(name=role_name)
                db.session.add(role)
                for p_name in permissions_list:
                    if p_name in all_permissions:
                        role.permissions.append(all_permissions[p_name])

            db.session.commit()
            print("--- [ОТЛАДКА] Роли и права успешно созданы. ---")
        else:
            print("--- [ОТЛАДКА] Роли уже существуют. Пропускаем создание. ---")

        print("--- [ОТЛАДКА] Проверка существования пользователя 'admin'... ---")
        if auth_models.User.query.filter_by(username='admin').first() is None:
            print("--- [ОТЛАДКА] Пользователь 'admin' не найден. Создание... ---")
            admin_role = auth_models.Role.query.filter_by(name='ADMIN').first()
            if admin_role:
                admin_user = auth_models.User(
                    username='admin',
                    role=admin_role,
                    full_name='Администратор Системы',
                    email='d.plakhotnyi@gh.uz'
                )
                admin_user.set_password('admin')
                db.session.add(admin_user)
                db.session.commit()
                print("--- [ОТЛАДКА] Пользователь 'admin' успешно создан. ---")
            else:
                print("--- [ОТЛАДКА] КРИТИЧЕСКАЯ ОШИБКА: Роль ADMIN не найдена! ---")
        else:
            print("--- [ОТЛАДКА] Пользователь 'admin' уже существует. ---")

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
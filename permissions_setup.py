"""Permission registry for apartment finder service (gateway integration)."""
from auth_connector import PermissionRegistry

permissions_registry = PermissionRegistry('finder')

# View permissions
permissions_registry.register('finder.view_selection', 'Просмотр системы подбора', 'Доступ к странице подбора квартир', 'view')
permissions_registry.register('finder.view_discounts', 'Просмотр системы скидок', 'Просмотр активной системы скидок', 'view')
permissions_registry.register('finder.view_version_history', 'Просмотр истории версий', 'Просмотр истории версий скидок', 'view')
permissions_registry.register('finder.view_plan_fact_report', 'Просмотр План-факт', 'Просмотр План-факт отчета', 'view')
permissions_registry.register('finder.view_inventory_report', 'Просмотр остатков', 'Просмотр отчета по остаткам', 'view')
permissions_registry.register('finder.view_manager_report', 'Просмотр отчетов менеджеров', 'Просмотр отчетов по менеджерам', 'view')
permissions_registry.register('finder.view_project_dashboard', 'Аналитика по проектам', 'Просмотр аналитики по проектам', 'view')

# Management permissions
permissions_registry.register('finder.manage_discounts', 'Управление скидками', 'Управление версиями скидок', 'manage')
permissions_registry.register('finder.manage_settings', 'Управление настройками', 'Управление настройками системы', 'manage')
permissions_registry.register('finder.manage_users', 'Управление пользователями', 'Управление пользователями системы', 'manage')
permissions_registry.register('finder.upload_data', 'Загрузка данных', 'Загрузка данных в систему', 'manage')
permissions_registry.register('finder.download_kpi_report', 'Выгрузка KPI', 'Выгрузка ведомости KPI менеджеров', 'manage')
permissions_registry.register('finder.manage_specials', 'Управление спец. предложениями', 'Управление специальными предложениями', 'manage')

# AI and advanced permissions
permissions_registry.register('finder.view_ai_forecast', 'AI прогнозы', 'Просмотр AI прогнозов', 'advanced')
permissions_registry.register('finder.manage_competitors', 'Управление конкурентами', 'Управление данными конкурентов', 'advanced')
permissions_registry.register('finder.manage_cancellations', 'Управление отменами', 'Управление отменами сделок', 'advanced')
permissions_registry.register('finder.manage_registry', 'Управление реестром', 'Управление реестром прогонов и спец. сделок', 'advanced')

# Mapping from old local permission names to gateway permission names
PERMISSION_MAP = {
    'view_selection': 'finder.view_selection',
    'view_discounts': 'finder.view_discounts',
    'view_version_history': 'finder.view_version_history',
    'view_plan_fact_report': 'finder.view_plan_fact_report',
    'view_inventory_report': 'finder.view_inventory_report',
    'view_manager_report': 'finder.view_manager_report',
    'view_project_dashboard': 'finder.view_project_dashboard',
    'manage_discounts': 'finder.manage_discounts',
    'manage_settings': 'finder.manage_settings',
    'manage_users': 'finder.manage_users',
    'upload_data': 'finder.upload_data',
    'download_kpi_report': 'finder.download_kpi_report',
    'manage_specials': 'finder.manage_specials',
    'view_ai_forecast': 'finder.view_ai_forecast',
    'manage_competitors': 'finder.manage_competitors',
    'manage_cancellations': 'finder.manage_cancellations',
    'manage_registry': 'finder.manage_registry',
}

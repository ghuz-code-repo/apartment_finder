"""Permission registry for apartment finder service (gateway integration).

Each UI element, button, menu item, and entity action has a dedicated permission
for granular access control. Permissions follow the naming convention:
    finder.{module}_{entity}_{action}
where action is one of: view, create, update, delete, export, import, calculate
"""
from auth_connector import PermissionRegistry

permissions_registry = PermissionRegistry('finder')

# ============================================================
# WILDCARD — все права сервиса одной строкой
# ============================================================
# Заменяет прежний обход по заголовку X-User-Admin: администратору выдаётся
# это право, и оно проходит обычной проверкой шаблона в permission_granted().
# Так в админке шлюза видно ровно то, что действует.
permissions_registry.register('finder.*', 'Все права сервиса', 'Полный доступ ко всем функциям finder', 'manage')

# ============================================================
# SELECTION MODULE — apartment search, details, commercial offers
# ============================================================
permissions_registry.register('finder.selection_view', 'Подбор: просмотр', 'Доступ к странице подбора квартир и поиску', 'view')
permissions_registry.register('finder.selection_details_view', 'Подбор: карточка объекта', 'Просмотр карточки квартиры', 'view')
permissions_registry.register('finder.selection_commercial_offer_view', 'Подбор: КП', 'Просмотр/печать коммерческого предложения', 'view')
permissions_registry.register('finder.selection_specials_view', 'Подбор: спецпредложения', 'Просмотр списка спецпредложений', 'view')

# ============================================================
# DISCOUNTS MODULE — discount overview, version control
# ============================================================
permissions_registry.register('finder.discounts_view', 'Скидки: просмотр', 'Просмотр активной системы скидок', 'view')
permissions_registry.register('finder.discounts_versions_view', 'Скидки: история версий', 'Просмотр истории версий скидок', 'view')
permissions_registry.register('finder.discounts_versions_create', 'Скидки: создание черновика', 'Создание новой черновой версии скидок', 'manage')
permissions_registry.register('finder.discounts_versions_update', 'Скидки: редактирование', 'Редактирование и активация версий скидок', 'manage')
permissions_registry.register('finder.discounts_versions_delete', 'Скидки: удаление версии', 'Удаление версии скидок', 'manage')
permissions_registry.register('finder.discounts_comment_create', 'Скидки: комментарии', 'Добавление комментариев к скидкам ЖК', 'manage')
permissions_registry.register('finder.discounts_import', 'Скидки: загрузка', 'Загрузка файла скидок из Excel', 'manage')
permissions_registry.register('finder.discounts_template_export', 'Скидки: шаблон', 'Скачивание шаблона скидок', 'manage')

# ============================================================
# REPORTS MODULE — plan-fact, financial model, funnel, quarterly, etc.
# ============================================================
permissions_registry.register('finder.reports_plan_fact_view', 'Отчеты: план-факт', 'Просмотр план-факт отчета', 'view')
permissions_registry.register('finder.reports_plan_fact_export', 'Отчеты: экспорт план-факт', 'Экспорт план-факт отчета в Excel', 'view')
permissions_registry.register('finder.reports_annual_plan_fact_export', 'Отчеты: годовой план-факт', 'Экспорт годового план-факт отчета', 'view')
permissions_registry.register('finder.reports_sales_funnel_view', 'Отчеты: воронка продаж', 'Просмотр воронки продаж', 'view')
permissions_registry.register('finder.reports_funnel_leads_view', 'Отчеты: лиды воронки', 'Просмотр лидов воронки продаж', 'view')
permissions_registry.register('finder.reports_financial_model_view', 'Отчеты: фин. модель', 'Просмотр финансовой модели', 'view')
permissions_registry.register('finder.reports_inventory_view', 'Отчеты: остатки', 'Просмотр сводки по остаткам', 'view')
permissions_registry.register('finder.reports_inventory_export', 'Отчеты: экспорт остатков', 'Экспорт сводки по остаткам в Excel', 'view')
permissions_registry.register('finder.reports_commercial_inventory_export', 'Отчеты: экспорт коммерции', 'Экспорт коммерческих остатков', 'view')
permissions_registry.register('finder.reports_deal_registry_view', 'Отчеты: реестр сделок', 'Просмотр реестра сделок', 'view')
permissions_registry.register('finder.reports_deal_registry_export', 'Отчеты: экспорт реестра', 'Экспорт реестра сделок в Excel', 'view')
permissions_registry.register('finder.reports_quarterly_view', 'Отчеты: квартальная', 'Просмотр квартальной аналитики', 'view')
permissions_registry.register('finder.reports_refund_view', 'Отчеты: возвраты', 'Просмотр отчета по возвратам', 'view')
permissions_registry.register('finder.reports_sales_pace_view', 'Отчеты: темпы продаж', 'Просмотр темпов продаж', 'view')
permissions_registry.register('finder.reports_expected_income_export', 'Отчеты: экспорт ожид. дохода', 'Экспорт деталей ожидаемого дохода', 'view')
permissions_registry.register('finder.reports_plan_import', 'Отчеты: загрузка плана', 'Загрузка плановых данных из Excel', 'manage')
permissions_registry.register('finder.reports_plan_template_export', 'Отчеты: шаблон плана', 'Скачивание шаблона плана', 'manage')

# ============================================================
# MANAGERS MODULE — performance, KPI, analytics, obligations
# ============================================================
permissions_registry.register('finder.managers_performance_view', 'Менеджеры: планы', 'Просмотр планов менеджеров', 'view')
permissions_registry.register('finder.managers_performance_detail_view', 'Менеджеры: детали плана', 'Детали плана менеджера', 'view')
permissions_registry.register('finder.managers_kpi_calculate', 'Менеджеры: расчет KPI', 'Расчет KPI менеджера', 'view')
permissions_registry.register('finder.managers_kpi_export', 'Менеджеры: выгрузка KPI', 'Выгрузка ведомости KPI', 'manage')
permissions_registry.register('finder.managers_analytics_view', 'Менеджеры: аналитика', 'Просмотр аналитики по менеджерам', 'view')
permissions_registry.register('finder.managers_yearly_view', 'Менеджеры: годовой отчет', 'Просмотр годового отчета менеджеров', 'view')
permissions_registry.register('finder.managers_leads_view', 'Менеджеры: лиды', 'Просмотр списка лидов', 'view')
permissions_registry.register('finder.managers_plan_import', 'Менеджеры: загрузка плана', 'Загрузка планов менеджеров из Excel', 'manage')
permissions_registry.register('finder.managers_plan_template_export', 'Менеджеры: шаблон плана', 'Скачивание шаблона плана менеджеров', 'manage')
permissions_registry.register('finder.managers_performance_view_own', 'Менеджеры: только свои планы', 'Просмотр плана и показателей только по себе', 'view')
permissions_registry.register('finder.managers_links_manage', 'Менеджеры: связка с пользователями', 'Сопоставление пользователей системы с менеджерами CRM', 'manage')
permissions_registry.register('finder.managers_hall_of_fame_view', 'Менеджеры: доска почета', 'Просмотр доски почета', 'view')
permissions_registry.register('finder.managers_obligations_view', 'Менеджеры: обязательства', 'Просмотр контроля обязательств', 'view')

# ============================================================
# PROJECTS MODULE — dashboard, passport, pricelist
# ============================================================
permissions_registry.register('finder.projects_dashboard_view', 'Проекты: дашборд', 'Просмотр дашборда проекта', 'view')
permissions_registry.register('finder.projects_passport_view', 'Проекты: паспорт', 'Просмотр паспорта проекта', 'view')
permissions_registry.register('finder.projects_passport_update', 'Проекты: ред. паспорта', 'Редактирование паспорта проекта', 'manage')
permissions_registry.register('finder.projects_pricelist_export', 'Проекты: прайс-лист', 'Генерация прайс-листов', 'manage')
permissions_registry.register('finder.projects_passport_export', 'Проекты: экспорт паспорта', 'Экспорт паспорта проекта в PPTX', 'view')
permissions_registry.register('finder.projects_competitor_import', 'Проекты: загрузка конкурентов', 'Загрузка данных конкурентов в паспорт', 'manage')
permissions_registry.register('finder.projects_competitor_template_export', 'Проекты: шаблон конкурентов', 'Скачивание шаблона конкурентов', 'manage')
permissions_registry.register('finder.projects_info_view', 'Проекты: информация о ЖК (просмотр)', 'Просмотр карточки ЖК, рендеров и характеристик — без изменения', 'view')
permissions_registry.register('finder.projects_info_update', 'Проекты: информация о ЖК', 'Настройка рендеров и характеристик ЖК', 'manage')

# ============================================================
# COMPETITORS MODULE — map, profiles, comparison, dynamics, media
# ============================================================
permissions_registry.register('finder.competitors_map_view', 'Конкуренты: карта', 'Просмотр карты конкурентов', 'view')
permissions_registry.register('finder.competitors_profile_view', 'Конкуренты: профиль', 'Просмотр профиля конкурента', 'view')
permissions_registry.register('finder.competitors_profile_update', 'Конкуренты: ред. профиля', 'Редактирование профиля конкурента', 'manage')
permissions_registry.register('finder.competitors_compare_view', 'Конкуренты: сравнение', 'Просмотр сравнения конкурентов', 'view')
permissions_registry.register('finder.competitors_dynamics_view', 'Конкуренты: динамика', 'Просмотр динамики рынка', 'view')
permissions_registry.register('finder.competitors_media_upload', 'Конкуренты: загрузка медиа', 'Загрузка медиафайлов конкурента', 'manage')
permissions_registry.register('finder.competitors_media_delete', 'Конкуренты: удаление медиа', 'Удаление медиафайлов конкурента', 'manage')
permissions_registry.register('finder.competitors_our_export', 'Конкуренты: экспорт наших', 'Экспорт данных наших ЖК', 'view')
permissions_registry.register('finder.competitors_our_import', 'Конкуренты: импорт наших', 'Импорт данных наших ЖК', 'manage')
permissions_registry.register('finder.competitors_external_export', 'Конкуренты: экспорт внешних', 'Экспорт данных конкурентов', 'view')
permissions_registry.register('finder.competitors_external_import', 'Конкуренты: импорт внешних', 'Импорт данных конкурентов', 'manage')
permissions_registry.register('finder.competitors_import_view', 'Конкуренты: страница импорта', 'Доступ к странице импорта', 'manage')

# ============================================================
# SPECIAL OFFERS MODULE
# ============================================================
permissions_registry.register('finder.specials_view', 'Спецпредложения: просмотр', 'Просмотр спецпредложений', 'view')
permissions_registry.register('finder.specials_create', 'Спецпредложения: создание', 'Создание спецпредложения', 'manage')
permissions_registry.register('finder.specials_update', 'Спецпредложения: редактирование', 'Редактирование и продление спецпредложений', 'manage')
permissions_registry.register('finder.specials_delete', 'Спецпредложения: удаление', 'Удаление спецпредложения', 'manage')

# ============================================================
# SETTINGS MODULE — calculator, currency, exclusions, email
# ============================================================
permissions_registry.register('finder.settings_calculator_view', 'Настройки: калькуляторы', 'Просмотр и изменение настроек калькуляторов', 'manage')
permissions_registry.register('finder.settings_currency_view', 'Настройки: курс валют', 'Просмотр и изменение курса валют', 'manage')
permissions_registry.register('finder.settings_exclusions_view', 'Настройки: исключения', 'Управление исключениями объектов', 'manage')
permissions_registry.register('finder.settings_inventory_exclusions_view', 'Настройки: искл. остатков', 'Управление исключениями остатков', 'manage')
permissions_registry.register('finder.settings_email_view', 'Настройки: email рассылка', 'Управление email получателями', 'manage')
permissions_registry.register('finder.settings_routes_view', 'Настройки: маршруты', 'Просмотр всех маршрутов системы', 'manage')
permissions_registry.register('finder.settings_zero_mortgage_template', 'Настройки: шаблон 0% ипотеки', 'Скачивание шаблонов нулевой ипотеки', 'manage')

# ============================================================
# USERS MODULE — management, roles
# ============================================================
permissions_registry.register('finder.users_view', 'Пользователи: просмотр', 'Просмотр списка пользователей', 'manage')
permissions_registry.register('finder.users_create', 'Пользователи: создание', 'Создание пользователей', 'manage')
permissions_registry.register('finder.users_delete', 'Пользователи: удаление', 'Удаление пользователей', 'manage')
permissions_registry.register('finder.roles_view', 'Роли: просмотр', 'Просмотр ролей', 'manage')
permissions_registry.register('finder.roles_create', 'Роли: создание', 'Создание ролей', 'manage')
permissions_registry.register('finder.roles_update', 'Роли: редактирование', 'Редактирование ролей', 'manage')
permissions_registry.register('finder.roles_delete', 'Роли: удаление', 'Удаление ролей', 'manage')

# ============================================================
# REGISTRY MODULE — special deals registry
# ============================================================
permissions_registry.register('finder.registry_view', 'Реестр: просмотр', 'Просмотр реестра спец. сделок', 'view')
permissions_registry.register('finder.registry_create', 'Реестр: добавление', 'Добавление записи в реестр', 'manage')
permissions_registry.register('finder.registry_delete', 'Реестр: удаление', 'Удаление записи из реестра', 'manage')

# ============================================================
# CANCELLATIONS MODULE
# ============================================================
permissions_registry.register('finder.cancellations_view', 'Расторжения: просмотр', 'Просмотр реестра расторжений', 'view')
permissions_registry.register('finder.cancellations_create', 'Расторжения: добавление', 'Добавление расторжения', 'manage')
permissions_registry.register('finder.cancellations_update', 'Расторжения: редактирование', 'Редактирование расторжений', 'manage')
permissions_registry.register('finder.cancellations_delete', 'Расторжения: удаление', 'Удаление расторжения', 'manage')
permissions_registry.register('finder.cancellations_export', 'Расторжения: экспорт', 'Экспорт расторжений в Excel', 'view')

# ============================================================
# NEWS MODULE — market news
# ============================================================
permissions_registry.register('finder.news_view', 'Новости: просмотр', 'Просмотр новостей рынка', 'view')
permissions_registry.register('finder.news_create', 'Новости: добавление', 'Добавление новости', 'manage')
permissions_registry.register('finder.news_delete', 'Новости: удаление', 'Удаление новости', 'manage')

# ============================================================
# AI MODULE — forecasts
# ============================================================
permissions_registry.register('finder.ai_forecast_view', 'AI: прогнозы', 'Просмотр AI прогнозов', 'advanced')
permissions_registry.register('finder.ai_train', 'AI: обучение', 'Запуск обучения модели', 'advanced')
permissions_registry.register('finder.ai_predict', 'AI: предсказание', 'Запуск прогнозирования', 'advanced')

# ============================================================
# COMPLEX CALCULATIONS MODULE
# ============================================================
permissions_registry.register('finder.complex_calc_view', 'Калькулятор: просмотр', 'Просмотр сложного калькулятора', 'view')
permissions_registry.register('finder.complex_calc_calculate', 'Калькулятор: расчет', 'Выполнение расчетов', 'view')
permissions_registry.register('finder.complex_calc_print', 'Калькулятор: печать КП', 'Печать КП из калькулятора', 'view')

# ============================================================
# MAPPING: short local names → full gateway permission names
# Used by @permission_required decorator and GatewayUserProxy.can()
# ============================================================
PERMISSION_MAP = {
    # Selection
    'selection_view': 'finder.selection_view',
    'selection_details_view': 'finder.selection_details_view',
    'selection_commercial_offer_view': 'finder.selection_commercial_offer_view',
    'selection_specials_view': 'finder.selection_specials_view',
    # Discounts
    'discounts_view': 'finder.discounts_view',
    'discounts_versions_view': 'finder.discounts_versions_view',
    'discounts_versions_create': 'finder.discounts_versions_create',
    'discounts_versions_update': 'finder.discounts_versions_update',
    'discounts_versions_delete': 'finder.discounts_versions_delete',
    'discounts_comment_create': 'finder.discounts_comment_create',
    'discounts_import': 'finder.discounts_import',
    'discounts_template_export': 'finder.discounts_template_export',
    # Reports
    'reports_plan_fact_view': 'finder.reports_plan_fact_view',
    'reports_plan_fact_export': 'finder.reports_plan_fact_export',
    'reports_annual_plan_fact_export': 'finder.reports_annual_plan_fact_export',
    'reports_sales_funnel_view': 'finder.reports_sales_funnel_view',
    'reports_funnel_leads_view': 'finder.reports_funnel_leads_view',
    'reports_financial_model_view': 'finder.reports_financial_model_view',
    'reports_inventory_view': 'finder.reports_inventory_view',
    'reports_inventory_export': 'finder.reports_inventory_export',
    'reports_commercial_inventory_export': 'finder.reports_commercial_inventory_export',
    'reports_deal_registry_view': 'finder.reports_deal_registry_view',
    'reports_deal_registry_export': 'finder.reports_deal_registry_export',
    'reports_quarterly_view': 'finder.reports_quarterly_view',
    'reports_refund_view': 'finder.reports_refund_view',
    'reports_sales_pace_view': 'finder.reports_sales_pace_view',
    'reports_expected_income_export': 'finder.reports_expected_income_export',
    'reports_plan_import': 'finder.reports_plan_import',
    'reports_plan_template_export': 'finder.reports_plan_template_export',
    # Managers
    'managers_performance_view': 'finder.managers_performance_view',
    'managers_performance_detail_view': 'finder.managers_performance_detail_view',
    'managers_kpi_calculate': 'finder.managers_kpi_calculate',
    'managers_kpi_export': 'finder.managers_kpi_export',
    'managers_analytics_view': 'finder.managers_analytics_view',
    'managers_yearly_view': 'finder.managers_yearly_view',
    'managers_leads_view': 'finder.managers_leads_view',
    'managers_plan_import': 'finder.managers_plan_import',
    'managers_plan_template_export': 'finder.managers_plan_template_export',
    'managers_performance_view_own': 'finder.managers_performance_view_own',
    'managers_links_manage': 'finder.managers_links_manage',
    'managers_hall_of_fame_view': 'finder.managers_hall_of_fame_view',
    'managers_obligations_view': 'finder.managers_obligations_view',
    # Projects
    'projects_dashboard_view': 'finder.projects_dashboard_view',
    'projects_passport_view': 'finder.projects_passport_view',
    'projects_passport_update': 'finder.projects_passport_update',
    'projects_pricelist_export': 'finder.projects_pricelist_export',
    'projects_passport_export': 'finder.projects_passport_export',
    'projects_competitor_import': 'finder.projects_competitor_import',
    'projects_competitor_template_export': 'finder.projects_competitor_template_export',
    'projects_info_view': 'finder.projects_info_view',
    'projects_info_update': 'finder.projects_info_update',
    # Competitors
    'competitors_map_view': 'finder.competitors_map_view',
    'competitors_profile_view': 'finder.competitors_profile_view',
    'competitors_profile_update': 'finder.competitors_profile_update',
    'competitors_compare_view': 'finder.competitors_compare_view',
    'competitors_dynamics_view': 'finder.competitors_dynamics_view',
    'competitors_media_upload': 'finder.competitors_media_upload',
    'competitors_media_delete': 'finder.competitors_media_delete',
    'competitors_our_export': 'finder.competitors_our_export',
    'competitors_our_import': 'finder.competitors_our_import',
    'competitors_external_export': 'finder.competitors_external_export',
    'competitors_external_import': 'finder.competitors_external_import',
    'competitors_import_view': 'finder.competitors_import_view',
    # Specials
    'specials_view': 'finder.specials_view',
    'specials_create': 'finder.specials_create',
    'specials_update': 'finder.specials_update',
    'specials_delete': 'finder.specials_delete',
    # Settings
    'settings_calculator_view': 'finder.settings_calculator_view',
    'settings_currency_view': 'finder.settings_currency_view',
    'settings_exclusions_view': 'finder.settings_exclusions_view',
    'settings_inventory_exclusions_view': 'finder.settings_inventory_exclusions_view',
    'settings_email_view': 'finder.settings_email_view',
    'settings_routes_view': 'finder.settings_routes_view',
    'settings_zero_mortgage_template': 'finder.settings_zero_mortgage_template',
    # Users
    'users_view': 'finder.users_view',
    'users_create': 'finder.users_create',
    'users_delete': 'finder.users_delete',
    'roles_view': 'finder.roles_view',
    'roles_create': 'finder.roles_create',
    'roles_update': 'finder.roles_update',
    'roles_delete': 'finder.roles_delete',
    # Registry
    'registry_view': 'finder.registry_view',
    'registry_create': 'finder.registry_create',
    'registry_delete': 'finder.registry_delete',
    # Cancellations
    'cancellations_view': 'finder.cancellations_view',
    'cancellations_create': 'finder.cancellations_create',
    'cancellations_update': 'finder.cancellations_update',
    'cancellations_delete': 'finder.cancellations_delete',
    'cancellations_export': 'finder.cancellations_export',
    # News
    'news_view': 'finder.news_view',
    'news_create': 'finder.news_create',
    'news_delete': 'finder.news_delete',
    # AI
    'ai_forecast_view': 'finder.ai_forecast_view',
    'ai_train': 'finder.ai_train',
    'ai_predict': 'finder.ai_predict',
    # Complex Calc
    'complex_calc_view': 'finder.complex_calc_view',
    'complex_calc_calculate': 'finder.complex_calc_calculate',
    'complex_calc_print': 'finder.complex_calc_print',
    # ============================================================
    # BACKWARD COMPATIBILITY: old permission names → new names
    # These ensure existing roles/code continue to work during migration
    # ============================================================
    'view_selection': 'finder.selection_view',
    'view_discounts': 'finder.discounts_view',
    'view_version_history': 'finder.discounts_versions_view',
    'view_plan_fact_report': 'finder.reports_plan_fact_view',
    'view_inventory_report': 'finder.reports_inventory_view',
    'view_manager_report': 'finder.managers_analytics_view',
    'view_project_dashboard': 'finder.projects_dashboard_view',
    'manage_discounts': 'finder.discounts_versions_update',
    'manage_settings': 'finder.settings_calculator_view',
    'manage_users': 'finder.users_view',
    'upload_data': 'finder.reports_plan_import',
    'download_kpi_report': 'finder.managers_kpi_export',
    'manage_specials': 'finder.specials_create',
    'view_ai_forecast': 'finder.ai_forecast_view',
    'manage_competitors': 'finder.competitors_map_view',
    'manage_cancellations': 'finder.cancellations_view',
    'manage_registry': 'finder.registry_view',
}

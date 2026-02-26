# app/web/api_routes.py

from datetime import date

from flask import Blueprint
from flask_restx import Api, Resource, fields, reqparse

from app.core.db_utils import get_planning_session
from app.core.decorators import permission_required
from app.models.planning_models import ProjectPassport, ProjectConstructionStage  # <-- ДОБАВИТЬ ЭТОТ ИМПОРТ
# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
# Импортируем PropertyType из его нового местоположения
from app.models.planning_models import PropertyType
# Импортируем все необходимые сервисы
from app.services import (
    selection_service,
    report_service,
    inventory_service,
    currency_service,
    discount_service
)

# 1. Создаем Blueprint
api_bp = Blueprint('api', __name__)

# 2. Инициализируем Flask-RESTx
api = Api(
    api_bp,
    version='1.0',
    title='ApartmentFinder API',
    description='API для мобильного приложения и внешних интеграций',
    doc='/docs/'
)

# ===================================================================
#          ПРОСТРАНСТВО ИМЕН ДЛЯ ПОДБОРА КВАРТИР
# ===================================================================
apartments_ns = api.namespace('apartments', description='Операции с квартирами')

search_model = apartments_ns.model('ApartmentSearchInput', {
    'budget': fields.Float(required=True, description='Сумма клиента', example=50000),
    'currency': fields.String(required=True, description='Валюта', enum=['USD', 'UZS'], example='USD'),
    'property_type_str': fields.String(required=True, description='Тип недвижимости', example='Квартира'),
    'floor': fields.String(description='Желаемый этаж', example='5'),
    'rooms': fields.String(description='Желаемое кол-во комнат', example='2'),
    'payment_method': fields.String(description='Вид оплаты', example='Ипотека')
})

@apartments_ns.route('/search')
class ApartmentSearchResource(Resource):
    @apartments_ns.expect(search_model, validate=True)
    def post(self):
        """Поиск квартир по бюджету и другим критериям"""
        data = api.payload
        results = selection_service.find_apartments_by_budget(
            budget=data.get('budget'),
            currency=data.get('currency'),
            property_type_str=data.get('property_type_str'),
            floor=data.get('floor'),
            rooms=data.get('rooms'),
            payment_method=data.get('payment_method')
        )
        return results

@apartments_ns.route('/<int:sell_id>')
@apartments_ns.response(404, 'Квартира не найдена')
@apartments_ns.param('sell_id', 'Идентификатор квартиры')
class ApartmentResource(Resource):
    def get(self, sell_id):
        """Получение детальной информации по ID квартиры"""
        card_data = selection_service.get_apartment_card_data(sell_id)
        if not card_data or not card_data.get('apartment'):
            return {'message': 'Квартира с таким ID не найдена'}, 404
        return card_data

# ===================================================================
#          ПРОСТРАНСТВО ИМЕН ДЛЯ ОТЧЕТНОСТИ
# ===================================================================
reports_ns = api.namespace('reports', description='Получение аналитических отчетов')

# --- План-факт отчет ---
plan_fact_parser = reqparse.RequestParser()
plan_fact_parser.add_argument('year', type=int, required=True, help='Год отчета', location='args')
plan_fact_parser.add_argument('month', type=int, required=True, help='Месяц отчета', location='args')
plan_fact_parser.add_argument('property_type', type=str, required=True, help='Тип недвижимости',
                              choices=[pt.value for pt in PropertyType], location='args') # Здесь используется PropertyType

@reports_ns.route('/plan-fact')
class PlanFactReportResource(Resource):
    @reports_ns.expect(plan_fact_parser)
    def get(self):
        """Возвращает детальный план-факт отчет"""
        args = plan_fact_parser.parse_args()
        report_data, totals = report_service.generate_plan_fact_report(
            args['year'], args['month'], args['property_type']
        )
        grand_totals = report_service.calculate_grand_totals(args['year'], args['month'])
        return {
            'details': report_data,
            'totals_by_type': totals,
            'grand_totals': grand_totals
        }

# --- Сводка по товарному запасу ---
inventory_parser = reqparse.RequestParser()
inventory_parser.add_argument('currency', type=str, default='UZS', choices=['UZS', 'USD'],
                              help='Валюта для отображения денежных значений', location='args')

@reports_ns.route('/inventory-summary')
class InventorySummaryResource(Resource):
    @reports_ns.expect(inventory_parser)
    def get(self):
        """Возвращает сводку по товарному запасу"""
        args = inventory_parser.parse_args()
        selected_currency = args['currency']
        summary_by_complex, overall_summary = inventory_service.get_inventory_summary_data()

        if selected_currency == 'USD':
            usd_rate = currency_service.get_current_effective_rate()
            if usd_rate and usd_rate > 0:
                for metrics in overall_summary.values():
                    metrics['total_value'] /= usd_rate
                    metrics['avg_price_m2'] /= usd_rate
                for complex_data in summary_by_complex.values():
                    for metrics in complex_data.values():
                        metrics['total_value'] /= usd_rate
                        metrics['avg_price_m2'] /= usd_rate
        return {
            'overall_summary': overall_summary,
            'summary_by_complex': summary_by_complex
        }

# ===================================================================
#          ПРОСТРАНСТВО ИМЕН ДЛЯ СКИДОК
# ===================================================================
discounts_ns = api.namespace('discounts', description='Просмотр системы скидок')

@discounts_ns.route('/overview')
class DiscountOverviewResource(Resource):
    @discounts_ns.doc('get_discounts_overview')
    def get(self):
        """Возвращает полную информацию по действующей системе скидок"""
        discounts_data = discount_service.get_discounts_with_summary()
        if not discounts_data:
            return {'message': 'Активная система скидок не найдена или пуста'}, 404
        return discounts_data


# ===================================================================
#          НОВЫЙ NAMESPACE ДЛЯ ПАСПОРТА ПРОЕКТА
# ===================================================================
passport_ns = api.namespace('passport', description='Операции с Паспортом проекта')

passport_model = passport_ns.model('ProjectPassportInput', {
    'complex_name': fields.String(required=True),
    'construction_type': fields.String,
    'address_link': fields.String,
    'heating_type': fields.String,
    'finishing_type': fields.String,
    'start_date': fields.String,
    'current_stage': fields.String,
    'project_manager': fields.String,
    'chief_engineer': fields.String,
    'sales_manager': fields.String,
    'planned_sales_pace': fields.Float(description='Плановый темп продаж (юнит/мес)')
})


@passport_ns.route('/save')
class PassportSaveResource(Resource):
    @passport_ns.expect(passport_model, validate=True)
    @permission_required('manage_settings')  # Используем право админа
    def post(self):
        """Сохраняет статические данные Паспорта проекта."""
        data = api.payload
        planning_session = get_planning_session()

        try:
            complex_name = data.get('complex_name')
            if not complex_name:
                return {'success': False, 'error': 'complex_name is required'}, 400

            passport = planning_session.query(ProjectPassport).get(complex_name)
            if not passport:
                passport = ProjectPassport(complex_name=complex_name)
                planning_session.add(passport)

            # Обновляем все поля
            passport.construction_type = data.get('construction_type')
            passport.address_link = data.get('address_link')
            passport.heating_type = data.get('heating_type')
            passport.finishing_type = data.get('finishing_type')
            passport.current_stage = data.get('current_stage')
            passport.project_manager = data.get('project_manager')
            passport.chief_engineer = data.get('chief_engineer')
            passport.sales_manager = data.get('sales_manager')
            passport.planned_sales_pace = data.get('planned_sales_pace')

            # Обрабатываем дату
            start_date_str = data.get('start_date')
            if start_date_str:
                try:
                    passport.start_date = date.fromisoformat(start_date_str)
                except ValueError:
                    passport.start_date = None
            else:
                passport.start_date = None

            planning_session.commit()
            return {'success': True, 'message': 'Паспорт проекта сохранен.'}

        except Exception as e:
            planning_session.rollback()
            return {'success': False, 'error': str(e)}, 500
        finally:
            planning_session.close()


stages_ns = api.namespace('passport/stages', description='Операции с этапами строительства Паспорта проекта')

# Модель для создания
stage_add_model = stages_ns.model('StageAddInput', {
    'complex_name': fields.String(required=True),
    'stage_name': fields.String(required=True),
    'start_date': fields.Date(nullable=True),
    'planned_end_date': fields.Date(nullable=True)
})

# Модель для обновления
stage_update_model = stages_ns.model('StageUpdateInput', {
    'stage_name': fields.String(required=True),
    'start_date': fields.Date(nullable=True),
    'planned_end_date': fields.Date(nullable=True),
    'actual_end_date': fields.Date(nullable=True)
})


@stages_ns.route('/add')
class StageAddResource(Resource):
    @stages_ns.expect(stage_add_model, validate=True)
    @permission_required('manage_settings')
    def post(self):
        """(ADMIN) Добавляет новый этап строительства."""
        data = api.payload
        planning_session = get_planning_session()
        try:
            # Проверяем, существует ли родительский паспорт
            passport = planning_session.query(ProjectPassport).get(data['complex_name'])
            if not passport:
                return {'success': False, 'error': 'ProjectPassport not found'}, 404

            new_stage = ProjectConstructionStage(
                complex_name=data['complex_name'],
                stage_name=data['stage_name'],
                start_date=date.fromisoformat(data['start_date']) if data.get('start_date') else None,
                planned_end_date=date.fromisoformat(data['planned_end_date']) if data.get('planned_end_date') else None
            )
            planning_session.add(new_stage)
            planning_session.commit()
            return {'success': True, 'stage': new_stage.to_dict()}
        except Exception as e:
            planning_session.rollback()
            return {'success': False, 'error': str(e)}, 500
        finally:
            planning_session.close()


@stages_ns.route('/update/<int:stage_id>')
class StageUpdateResource(Resource):
    @stages_ns.expect(stage_update_model, validate=True)
    @permission_required('manage_settings')
    def post(self, stage_id):
        """(ADMIN) Обновляет существующий этап строительства."""
        data = api.payload
        planning_session = get_planning_session()
        try:
            stage = planning_session.query(ProjectConstructionStage).get(stage_id)
            if not stage:
                return {'success': False, 'error': 'Stage not found'}, 404

            stage.stage_name = data.get('stage_name', stage.stage_name)
            stage.start_date = date.fromisoformat(data['start_date']) if data.get('start_date') else None
            stage.planned_end_date = date.fromisoformat(data['planned_end_date']) if data.get(
                'planned_end_date') else None
            stage.actual_end_date = date.fromisoformat(data['actual_end_date']) if data.get('actual_end_date') else None

            planning_session.commit()
            return {'success': True, 'stage': stage.to_dict()}
        except Exception as e:
            planning_session.rollback()
            return {'success': False, 'error': str(e)}, 500
        finally:
            planning_session.close()


@stages_ns.route('/delete/<int:stage_id>')
class StageDeleteResource(Resource):
    @permission_required('manage_settings')
    def post(self, stage_id):
        """(ADMIN) Удаляет этап строительства."""
        planning_session = get_planning_session()
        try:
            stage = planning_session.query(ProjectConstructionStage).get(stage_id)
            if not stage:
                return {'success': False, 'error': 'Stage not found'}, 404

            planning_session.delete(stage)
            planning_session.commit()
            return {'success': True, 'message': 'Stage deleted'}
        except Exception as e:
            planning_session.rollback()
            return {'success': False, 'error': str(e)}, 500
        finally:
            planning_session.close()

# --- НЕ ЗАБУДЬТЕ ЗАРЕГИСТРИРОВАТЬ НОВЫЙ NAMESPACE ---

api.add_namespace(passport_ns)
api.add_namespace(stages_ns)
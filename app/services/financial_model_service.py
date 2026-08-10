# app/services/financial_model_service.py

from sqlalchemy import func, extract, or_
from ..core.db_utils import get_planning_session, get_mysql_session
from ..models import planning_models, finance_models, estate_models
from . import currency_service  # Импорт сервиса валют


def get_financial_model_data(complex_name):
    planning_session = get_planning_session()
    mysql_session = get_mysql_session()

    try:
        clean_name = complex_name.strip()
        # Получаем эффективный курс
        usd_rate = currency_service.get_current_effective_rate() or 1.0

        target = planning_session.query(planning_models.ProjectFinancialTarget).filter(
            func.lower(planning_models.ProjectFinancialTarget.complex_name) == clean_name.lower()
        ).first()

        if not target:
            return None

        # Факт выручки (MySQL)
        fact_revenue = mysql_session.query(func.sum(finance_models.FinanceOperation.summa)).join(
            estate_models.EstateSell, finance_models.FinanceOperation.estate_sell_id == estate_models.EstateSell.id
        ).join(
            estate_models.EstateHouse, estate_models.EstateSell.house_id == estate_models.EstateHouse.id
        ).filter(
            func.trim(estate_models.EstateHouse.complex_name) == clean_name,
            finance_models.FinanceOperation.status_name == "Проведено",
            or_(
                # Применение .notin_() вместо !=
                finance_models.FinanceOperation.payment_type.notin_([
                    "Возврат поступлений при отмене сделки",
                    "Возврат при уменьшении стоимости",
                    "безучпоступление",
                    "Уступка права требования",
                    "Бронь"
                ]),
                finance_models.FinanceOperation.payment_type.is_(None)
            )
        ).scalar() or 0.0

        # Остаток площади: статусы из inventory_service
        valid_statuses = ["Маркетинговый резерв", "Подбор", "Бронь"]
        remaining_area_res = mysql_session.query(func.sum(estate_models.EstateSell.estate_area)).join(
            estate_models.EstateHouse, estate_models.EstateSell.house_id == estate_models.EstateHouse.id
        ).filter(
            func.trim(estate_models.EstateHouse.complex_name) == clean_name,
            estate_models.EstateSell.estate_sell_status_name.in_(valid_statuses),
            estate_models.EstateSell.estate_area > 0
        ).scalar()

        remaining_area = float(remaining_area_res) if remaining_area_res else 0.0

        # Расчет целей
        total_target_revenue = (target.total_construction_budget * (
                    1 + target.target_margin_percent / 100)) + target.estimated_other_costs
        remaining_target_revenue = max(0, total_target_revenue - fact_revenue)
        rec_price_m2 = remaining_target_revenue / remaining_area if remaining_area > 0 else 0

        # Юнит-экономика
        unit_econ_query = mysql_session.query(
            estate_models.EstateSell.estate_sell_category,
            func.sum(finance_models.FinanceOperation.summa).label('revenue'),
            func.count(func.distinct(estate_models.EstateSell.id)).label('units'),
            func.sum(estate_models.EstateSell.estate_area).label('area')
        ).join(finance_models.FinanceOperation,
               finance_models.FinanceOperation.estate_sell_id == estate_models.EstateSell.id) \
            .join(estate_models.EstateHouse, estate_models.EstateSell.house_id == estate_models.EstateHouse.id) \
            .filter(
            func.trim(estate_models.EstateHouse.complex_name) == clean_name,
            finance_models.FinanceOperation.status_name == "Проведено"
        ).group_by(estate_models.EstateSell.estate_sell_category).all()

        unit_economics = []
        for r in unit_econ_query:
            if not r[0]: continue
            cat_name = planning_models.map_mysql_key_to_russian_value(r[0])
            unit_economics.append({
                "category": cat_name,
                "revenue": float(r.revenue or 0),
                "units": int(r.units or 0),
                "area": float(r.area or 0),
                "avg_price": float(r.revenue / r.area) if r.area and r.area > 0 else 0
            })

        # Помесячный факт поступлений
        monthly_flow_res = mysql_session.query(
            extract('year', finance_models.FinanceOperation.date_added).label('y'),
            extract('month', finance_models.FinanceOperation.date_added).label('m'),
            func.sum(finance_models.FinanceOperation.summa).label('rev')
        ).join(estate_models.EstateSell).join(estate_models.EstateHouse).filter(
            func.trim(estate_models.EstateHouse.complex_name) == clean_name,
            finance_models.FinanceOperation.status_name == "Проведено"
        ).group_by('y', 'm').order_by('y', 'm').all()

        return {
            "target": target,
            "metrics": {
                "fact_revenue": float(fact_revenue),
                "remaining_area": remaining_area,
                "recommended_price": float(rec_price_m2),
                "total_target_revenue": float(total_target_revenue),
                "completion_percent": (fact_revenue / total_target_revenue * 100) if total_target_revenue > 0 else 0
            },
            "unit_economics": unit_economics,
            "monthly_flow": [{"year": int(f.y), "month": int(f.m), "revenue": float(f.rev)} for f in monthly_flow_res],
            "usd_rate": usd_rate
        }
    finally:
        planning_session.close()
        mysql_session.close()
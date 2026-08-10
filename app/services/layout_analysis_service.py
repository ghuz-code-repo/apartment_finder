from collections import defaultdict
from sqlalchemy import func
from app.models.estate_models import EstateSell, EstateDeal
from app.models import planning_models
from app.models.planning_models import map_russian_to_mysql_key


class LayoutAnalysisService:
    @staticmethod
    def get_layout_analysis(complex_name, house_ids, mysql_prop_key, active_version, planning_session, mysql_session,
                            sold_statuses, VALID_STATUSES):
        """
        Собирает единую статистику по планировкам: продажи, остатки и цена дна.
        """
        layout_map = defaultdict(lambda: {
            'sold': 0,
            'inventory': 0,
            'total_price_bottom': 0.0,
            'total_area': 0.0
        })

        # 1. Расчет коэффициента скидки для "цены дна"
        discount_rate = 0
        if active_version:
            d = planning_session.query(planning_models.Discount).filter_by(
                version_id=active_version.id,
                complex_name=complex_name,
                property_type=planning_models.PropertyType.FLAT,
                payment_method=planning_models.PaymentMethod.FULL_PAYMENT
            ).first()
            if d:
                discount_rate = (d.mpp or 0) + (d.rop or 0) + (d.kd or 0) + (d.action or 0)

        # 2. Сбор данных по остаткам (Inventory)
        inv_q = mysql_session.query(EstateSell).filter(
            EstateSell.house_id.in_(house_ids),
            EstateSell.estate_sell_status_name.in_(VALID_STATUSES)
        )
        if mysql_prop_key:
            inv_q = inv_q.filter(EstateSell.estate_sell_category == mysql_prop_key)

        for unit in inv_q.all():
            name = unit.flatClass or "Не указано"
            layout_map[name]['inventory'] += 1

            # Расчет цены дна для остатка
            if unit.estate_price and unit.estate_area and unit.estate_price > 3_000_000:
                price_bottom = (unit.estate_price - 3_000_000) * (1 - discount_rate)
                layout_map[name]['total_price_bottom'] += price_bottom
                layout_map[name]['total_area'] += unit.estate_area

        # 3. Сбор данных по продажам (Sales)
        sales_q = mysql_session.query(EstateSell.flatClass).join(EstateDeal).filter(
            EstateSell.house_id.in_(house_ids),
            EstateDeal.deal_status_name.in_(sold_statuses)
        )
        if mysql_prop_key:
            sales_q = sales_q.filter(EstateSell.estate_sell_category == mysql_prop_key)

        for row in sales_q.all():
            name = row[0] or "Не указано"
            layout_map[name]['sold'] += 1

        # 4. Формирование финального списка
        results = []
        for name, data in layout_map.items():
            avg_bottom = data['total_price_bottom'] / data['total_area'] if data['total_area'] > 0 else 0
            results.append({
                'name': name,
                'sold': data['sold'],
                'inventory': data['inventory'],
                'total': data['sold'] + data['inventory'],
                'avg_bottom': avg_bottom
            })

        # Сортировка по популярности (количеству продаж)
        return sorted(results, key=lambda x: x['sold'], reverse=True)
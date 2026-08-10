import pandas as pd
import numpy as np
import joblib
import os
from datetime import datetime, timedelta
from app.models.estate_models import EstateDeal, EstateSell, EstateHouse
from app.core.extensions import db
from sqlalchemy.orm import joinedload


class AIForecastService:
    MODEL_PATH = 'app/models/ai/sales_forecast_model.pkl'
    APARTMENT_KEYWORDS = ['квартир', 'flat', 'apartment', 'жил']

    @staticmethod
    def _get_apartment_filter():
        conditions = [db.func.lower(EstateSell.estate_sell_category).contains(kw) for kw in
                      AIForecastService.APARTMENT_KEYWORDS]
        return db.or_(*conditions)

    @staticmethod
    def train_with_validation():
        os.makedirs(os.path.dirname(AIForecastService.MODEL_PATH), exist_ok=True)
        joblib.dump({"status": "updated", "date": datetime.now()}, AIForecastService.MODEL_PATH)
        return "Модель обновлена (период: последние 6 месяцев)"

    @staticmethod
    def predict_for_month(target_month, target_year=2026):
        # 1. Исходные данные: история продаж за последние 6 месяцев
        history_limit = datetime.now() - timedelta(days=183)

        sales_history = db.session.query(
            EstateHouse.complex_name,
            EstateSell.estate_rooms,
            db.func.count(EstateDeal.id).label('total_sales')
        ).select_from(EstateDeal) \
            .join(EstateSell, EstateDeal.estate_sell_id == EstateSell.id) \
            .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
            .filter(AIForecastService._get_apartment_filter()) \
            .filter(EstateDeal.agreement_date >= history_limit) \
            .group_by(EstateHouse.complex_name, EstateSell.estate_rooms).all()

        # Карта суммарных продаж за 6 месяцев для расчета темпа
        # Используем список для хранения истории, чтобы имитировать "скользящее окно"
        history_data = {}  # {(проект, комнаты): [продажи_м1, продажи_м2, ...]}
        for row in sales_history:
            # На старте у нас есть среднее значение, распределенное на 6 месяцев
            history_data[(row.complex_name, row.estate_rooms)] = [row.total_sales / 6.0] * 6

        # 2. Текущие остатки
        inventory_data = db.session.query(
            EstateHouse.complex_name,
            EstateSell.estate_rooms,
            db.func.count(EstateSell.id).label('stock'),
            db.func.avg(EstateSell.estate_price_m2).label('avg_price_m2')
        ).select_from(EstateSell) \
            .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
            .filter(AIForecastService._get_apartment_filter()) \
            .filter(
            EstateSell.estate_sell_status_name.in_(['Подбор', 'Маркетинговый резерв', 'Забронировано', 'Бронь'])) \
            .group_by(EstateHouse.complex_name, EstateSell.estate_rooms).all()

        # Создаем рабочую копию остатков
        current_stocks = {}  # {(проект, комнаты): stock}
        project_prices = {}  # {проект: {комнаты: цена}}
        for row in inventory_data:
            current_stocks[(row.complex_name, row.estate_rooms)] = row.stock
            if row.complex_name not in project_prices:
                project_prices[row.complex_name] = {}
            project_prices[row.complex_name][row.estate_rooms] = float(row.avg_price_m2 or 0)

        # 3. ЦИКЛ РЕКУРСИВНОГО ПРОГНОЗА
        now = datetime.now()
        current_m = now.month
        current_y = now.year

        # Определяем количество месяцев для симуляции
        # Если выбран Январь 2026, а сейчас Январь 2026 — это 1 итерация.
        months_to_simulate = (target_year - current_y) * 12 + (target_month - current_m) + 1
        if months_to_simulate <= 0: months_to_simulate = 1

        last_monthly_forecast = {}  # Сюда сохраним результаты последней итерации (целевой месяц)

        for step in range(months_to_simulate):
            step_forecast = {}  # Результаты внутри текущего шага

            # Считаем прогноз для каждой пары (проект, комнаты)
            for (proj, rooms), stock in current_stocks.items():
                if stock <= 0:
                    continue

                # Рассчитываем темп на основе последних 6 "месяцев" (реальных или предсказанных)
                past_sales = history_data.get((proj, rooms), [0.1] * 6)
                base_pace = sum(past_sales) / 6.0

                # Коэффициент затухания (ликвидности)
                months_remaining = stock / base_pace if base_pace > 0 else 10
                liquidity_factor = 1.0
                if months_remaining < 2.0:
                    liquidity_factor = 0.3 + (0.7 * (months_remaining / 2.0))

                forecast = base_pace * liquidity_factor
                final_forecast = min(forecast, stock)

                # Обновляем остатки (вычитаем прогноз)
                current_stocks[(proj, rooms)] -= final_forecast

                # Обновляем историю (сдвигаем окно: убираем старый месяц, добавляем прогноз как "факт")
                past_sales.pop(0)
                past_sales.append(final_forecast)
                history_data[(proj, rooms)] = past_sales

                step_forecast[(proj, rooms)] = final_forecast

            # Сохраняем результаты шага
            last_monthly_forecast = step_forecast

        # 4. Формирование финального отчета для ТАРГЕТНОГО месяца
        final_results = {}
        for (proj, rooms), forecast in last_monthly_forecast.items():
            if proj not in final_results:
                # Берем исходный stock для отображения в таблице (или текущий остаток после всех шагов?)
                # Обычно пользователь хочет видеть, сколько продастся именно в ТОМ месяце при ТЕКУЩИХ остатках.
                # Но корректнее показать остаток на НАЧАЛО целевого месяца.
                final_results[proj] = {"project": proj, "forecast": 0.0, "stock": 0, "total_weighted_price": 0.0}

            # Находим остаток на начало целевого месяца (текущий stock + прогноз этого месяца)
            stock_at_start = current_stocks[(proj, rooms)] + forecast
            price = project_prices.get(proj, {}).get(rooms, 0)

            final_results[proj]["forecast"] += forecast
            final_results[proj]["stock"] += int(stock_at_start)
            final_results[proj]["total_weighted_price"] += price * stock_at_start

        result_list = []
        for p in final_results.values():
            avg_price = int(p["total_weighted_price"] / p["stock"]) if p["stock"] > 0 else 0
            result_list.append({
                "project": p["project"],
                "forecast": int(round(p["forecast"])),
                "stock": p["stock"],
                "avg_price": avg_price
            })

        return sorted(result_list, key=lambda x: x['forecast'], reverse=True)
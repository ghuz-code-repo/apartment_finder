# app/services/manager_report_service.py
import openpyxl
from sqlalchemy import or_
import pandas as pd
import re
from datetime import datetime, date
from collections import defaultdict
from sqlalchemy import func, extract
import io

from ..core.db_utils import get_planning_session, get_mysql_session

# Обновленные импорты
from app.models import auth_models
from app.models import planning_models
from app.models.estate_models import EstateDeal, EstateSell, EstateHouse
from app.models.finance_models import FinanceOperation
from app.services import currency_service


def process_manager_plans_from_excel(file_path: str):
    """
    Обрабатывает Excel-файл с персональными планами менеджеров.
    """
    df = pd.read_excel(file_path)
    plans_to_save = defaultdict(lambda: defaultdict(float))
    # В регулярном выражении оставляем только "поступления"
    header_pattern = re.compile(r"(поступления) (\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    planning_session = get_planning_session()

    managers_map = {m.full_name: m.id for m in mysql_session.query(auth_models.SalesManager).all()}

    for index, row in df.iterrows():
        manager_name = row.iloc[0]
        if manager_name not in managers_map:
            print(f"[MANAGER PLANS] ⚠️ ВНИМАНИЕ: Менеджер '{manager_name}' не найден в базе. Строка пропущена.")
            continue
        manager_id = managers_map[manager_name]

        for col_name, value in row.iloc[1:].items():
            if pd.isna(value) or value == 0:
                continue
            match = header_pattern.search(str(col_name))
            if not match:
                continue

            # Логика упрощена, так как у нас только один тип плана
            plan_type_str = match.group(1)
            date_str = match.group(2)
            plan_date = datetime.strptime(date_str, '%d.%m.%Y')
            year, month = plan_date.year, plan_date.month

            if 'поступления' in plan_type_str.lower():
                plans_to_save[(manager_id, year, month)]['plan_income'] += float(value)

    updated_count, created_count = 0, 0
    for (manager_id, year, month), values in plans_to_save.items():
        plan_entry = planning_session.query(planning_models.ManagerSalesPlan).filter_by(  # <--- ИЗМЕНЕНО
            manager_id=manager_id, year=year, month=month
        ).first()
        if not plan_entry:
            plan_entry = planning_models.ManagerSalesPlan(manager_id=manager_id, year=year, month=month)
            planning_session.add(plan_entry)  # <--- ИЗМЕНЕНО
            created_count += 1

        # Устанавливаем plan_volume в 0, обновляем только plan_income
        plan_entry.plan_volume = 0.0
        plan_entry.plan_income = values.get('plan_income', 0.0)
        updated_count += 1

    planning_session.commit()
    return f"Успешно обработано планов: создано {created_count}, обновлено {updated_count}."


def get_manager_performance_details(manager_id: int, year: int):
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    planning_session = get_planning_session()
    """
    Собирает детальную информацию по выполнению плана для одного менеджера за год,
    ЗАРАНЕЕ РАССЧИТЫВАЯ KPI ДЛЯ КАЖДОГО МЕСЯЦА.
    """
    manager = mysql_session.query(auth_models.SalesManager).get(manager_id)
    if not manager:
        return None

    plans_query = planning_session.query(planning_models.ManagerSalesPlan).filter_by(manager_id=manager_id,
                                                                                     year=year).all()  # <--- ИЗМЕНЕНО
    plan_data = {p.month: p for p in plans_query}

    effective_date = func.coalesce(EstateDeal.agreement_date, EstateDeal.preliminary_date)
    fact_volume_query = mysql_session.query(
        extract('month', effective_date).label('month'),
        func.sum(EstateDeal.deal_sum).label('fact_volume')
    ).filter(
        EstateDeal.deal_manager_id == manager_id,
        extract('year', effective_date) == year,
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).group_by('month').all()
    fact_volume_data = {row.month: row.fact_volume or 0 for row in fact_volume_query}

    fact_income_query = mysql_session.query(
        extract('month', FinanceOperation.date_added).label('month'),
        func.sum(FinanceOperation.summa).label('fact_income')
    ).filter(
        FinanceOperation.manager_id == manager_id,
        extract('year', FinanceOperation.date_added) == year,
        FinanceOperation.status_name == "Проведено",
        or_(
            FinanceOperation.payment_type.notin_([
                "Возврат поступлений при отмене сделки",
                "Возврат при уменьшении стоимости",
                "безучпоступление",
                "Уступка права требования",
                "Бронь"
            ]),
            FinanceOperation.payment_type.is_(None)
        )
    ).group_by('month').all()
    fact_income_data = {row.month: row.fact_income or 0 for row in fact_income_query}

    report = []
    for month_num in range(1, 13):
        plan = plan_data.get(month_num)
        fact_volume = fact_volume_data.get(month_num, 0)
        fact_income = fact_income_data.get(month_num, 0)
        plan_income = plan.plan_income if plan else 0.0

        # --- ГЛАВНОЕ ИЗМЕНЕНИЕ: РАССЧИТЫВАЕМ KPI ПРЯМО ЗДЕСЬ ---
        kpi_bonus = calculate_manager_kpi(plan_income, fact_income)

        report.append({
            'month': month_num,
            'plan_volume': plan.plan_volume if plan else 0,
            'fact_volume': fact_volume,
            'volume_percent': (fact_volume / plan.plan_volume * 100) if (plan and plan.plan_volume > 0) else 0,
            'plan_income': plan_income,
            'fact_income': fact_income,
            'income_percent': (fact_income / plan_income * 100) if (plan and plan_income > 0) else 0,
            'kpi_bonus': kpi_bonus  # <-- И ДОБАВЛЯЕМ РЕЗУЛЬТАТ В ДАННЫЕ
        })

    return {'manager_id': manager_id, 'manager_name': manager.full_name, 'performance': report}


def generate_manager_plan_template_excel():
    """
    Генерирует Excel-файл с ФИО всех менеджеров и столбцами планов на текущий год.
    """
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    managers = mysql_session.query(auth_models.SalesManager).order_by(
        auth_models.SalesManager.full_name).all()  # <--- ИЗМЕНЕНО
    manager_names = [manager.full_name for manager in managers]

    current_year = date.today().year
    headers = ['ФИО']
    # В цикле убираем добавление столбца "Контрактация"
    for month in range(1, 13):
        date_str = f"01.{month:02d}.{current_year}"
        headers.append(f"Поступления {date_str}")

    data = [{'ФИО': name, **{header: 0 for header in headers[1:]}} for name in manager_names]

    df = pd.DataFrame(data, columns=headers)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Шаблон планов')
        worksheet = writer.sheets['Шаблон планов']
        worksheet.column_dimensions['A'].width = 35
        for i in range(1, len(headers)):
            col_letter = openpyxl.utils.get_column_letter(i + 1)
            worksheet.column_dimensions[col_letter].width = 25
    output.seek(0)
    return output


def calculate_manager_kpi(plan_income: float, fact_income: float) -> float:
    if not plan_income or plan_income == 0:
        return 0.0  # Если плана не было, премии нет

    completion_percentage = (fact_income / plan_income) * 100

    if completion_percentage >= 100:
        bonus = fact_income * 0.005
    elif completion_percentage >= 90:
        bonus = fact_income * 0.004
    elif completion_percentage >= 80:
        bonus = fact_income * 0.003
    else:
        bonus = 0.0

    return bonus


def generate_kpi_report_excel(year: int, month: int):
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    """
    
    Создает детализированный и отформатированный отчет по KPI менеджеров в формате Excel.
    (Исправленная версия с правильным порядком колонок и формулами)
    """
    # 1. Получаем актуальный курс доллара
    usd_rate = currency_service.get_current_effective_rate()
    if not usd_rate or usd_rate == 0:
        raise ValueError("Не удалось получить актуальный курс USD.")

    # 2. ШАГ А: Получаем все планы из базы `planning_db` за указанный период
    plans = planning_session.query(planning_models.ManagerSalesPlan).filter(
        planning_models.ManagerSalesPlan.year == year,
        planning_models.ManagerSalesPlan.month == month,
        planning_models.ManagerSalesPlan.plan_income > 0
    ).all()

    if not plans:
        return None  # Если нет планов, возвращаем None

    manager_ids_with_plans = [p.manager_id for p in plans]
    plans_map = {p.manager_id: p for p in plans}

    # 3. ШАГ Б: Получаем из основной базы данных всех менеджеров, чьи ID мы нашли
    managers = mysql_session.query(auth_models.SalesManager).filter(
        auth_models.SalesManager.id.in_(manager_ids_with_plans)
    ).order_by(auth_models.SalesManager.full_name).all()

    # 4. Собираем исходные данные, объединяя результаты в Python
    source_data = []
    for manager in managers:
        plan = plans_map.get(manager.id)
        if not plan:
            continue

        fact_income_query = mysql_session.query(
            func.sum(FinanceOperation.summa)
        ).filter(
            FinanceOperation.manager_id == manager.id,
            extract('year', FinanceOperation.date_added) == year,
            extract('month', FinanceOperation.date_added) == month,
            FinanceOperation.status_name == "Проведено",
            or_(
                # Замена != на .notin_()
                FinanceOperation.payment_type.notin_([
                    "Возврат поступлений при отмене сделки",
                    "Возврат при уменьшении стоимости",
                    "безучпоступление",
                    "Уступка права требования",
                    "Бронь"
                ]),
                FinanceOperation.payment_type.is_(None)
            )
        ).scalar()

        fact_income = fact_income_query or 0.0
        kpi_bonus_uzs = calculate_manager_kpi(plan.plan_income, fact_income)

        source_data.append({
            "full_name": manager.full_name,
            "plan_uzs": plan.plan_income,
            "fact_uzs": fact_income,
            "kpi_bonus_uzs": kpi_bonus_uzs,
            "kpi_bonus_usd": kpi_bonus_uzs / usd_rate
        })

    # 5. Формируем DataFrame в строгом соответствии с вашим ТЗ
    final_report_rows = []
    for i, data in enumerate(source_data):
        final_report_rows.append({
            '№': i + 1,
            'ФИО менеджера': data['full_name'],
            'Должность': 'Менеджер по продажам',
            'Личный план продаж на период (долл. США)': data['plan_uzs'] / usd_rate,
            'Факт выполнения личного плана продаж на период (долл. США)': data['fact_uzs'] / usd_rate,
            '% выполнения личного плана продаж': (data['fact_uzs'] / data['plan_uzs']) if data['plan_uzs'] > 0 else 0,
            'Удовлетворенность работой сотрудника (коэф.)': None,
            'Итоговая сумма к выплате, NET (долл. США)': None,  # Placeholder
            'Итоговая сумма к выплате, NET (сум)': None,  # Placeholder
            'Итоговая сумма к выплате, GROSS (сум)': None  # Placeholder
        })

    df = pd.DataFrame(final_report_rows)

    # 6. Создаем и форматируем Excel-файл
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Ведомость KPI', index=False, startrow=1)

        workbook = writer.book
        worksheet = writer.sheets['Ведомость KPI']

        # Форматы ячеек и заголовков
        header_format = workbook.add_format(
            {'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#D7E4BC', 'border': 1, 'align': 'center'})
        money_usd_format = workbook.add_format({'num_format': '$#,##0.00', 'border': 1})
        money_uzs_format = workbook.add_format({'num_format': '#,##0', 'border': 1})
        percent_format = workbook.add_format({'num_format': '0.0%', 'border': 1})
        coef_format = workbook.add_format({'bg_color': '#FFFFCC', 'border': 1})
        title_format = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})

        month_names = {1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь', 7: 'Июль', 8: 'Август',
                       9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'}
        worksheet.merge_range('A1:J1', f'Ведомость по KPI за {month_names.get(month, "")} {year}', title_format)

        for col_num, value in enumerate(df.columns):
            worksheet.write(1, col_num, value, header_format)

        # Ширина и формат колонок
        worksheet.set_column('A:A', 5)
        worksheet.set_column('B:B', 35)
        worksheet.set_column('C:C', 25)
        worksheet.set_column('D:E', 20, money_usd_format)
        worksheet.set_column('F:F', 15, percent_format)
        worksheet.set_column('G:G', 25, coef_format)
        worksheet.set_column('H:H', 25, money_usd_format)
        worksheet.set_column('I:I', 25, money_uzs_format)
        worksheet.set_column('J:J', 25, money_uzs_format)

        # 7. Вставляем формулы
        for idx, data in enumerate(source_data):
            row_num = idx + 3
            kpi_usd = data['kpi_bonus_usd']
            kpi_uzs = data['kpi_bonus_uzs']

            worksheet.write_formula(f'H{row_num}', f'=IF(ISBLANK(G{row_num}),0,{kpi_usd}*G{row_num})')
            worksheet.write_formula(f'I{row_num}', f'=IF(ISBLANK(G{row_num}),0,{kpi_uzs}*G{row_num})')
            worksheet.write_formula(f'J{row_num}', f'=IF(ISBLANK(I{row_num}),0,I{row_num}/0.88)')

    output.seek(0)
    return output


def get_manager_kpis(manager_id: int, year: int):
    """
    Рассчитывает расширенные KPI для одного менеджера на основе ПОСТУПЛЕНИЙ.
    """
    # Запрос для "Любимого ЖК" остается по количеству сделок
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО

    best_complex_query = mysql_session.query(
        EstateHouse.complex_name, func.count(EstateDeal.id).label('deal_count')
    ).join(EstateSell, EstateHouse.sells).join(EstateDeal, EstateSell.deals) \
        .filter(
        EstateDeal.deal_manager_id == manager_id,
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).group_by(EstateHouse.complex_name).order_by(func.count(EstateDeal.id).desc()).first()

    # Запрос для "Продано юнитов" остается по количеству сделок
    units_by_type_query = mysql_session.query(
        EstateSell.estate_sell_category, func.count(EstateDeal.id).label('unit_count')
    ).join(EstateDeal, EstateSell.deals).filter(
        EstateDeal.deal_manager_id == manager_id,
        EstateDeal.deal_status_name.in_(["Сделка в работе", "Сделка проведена"])
    ).group_by(EstateSell.estate_sell_category).all()

    # Все расчеты рекордов переведены на поступления

    # Лучший год по ПОСТУПЛЕНИЯМ
    best_year_income_query = mysql_session.query(
        extract('year', FinanceOperation.date_added).label('income_year'),
        func.sum(FinanceOperation.summa).label('total_income')
    ).filter(
        FinanceOperation.manager_id == manager_id,
        FinanceOperation.status_name == 'Проведено'
    ).group_by('income_year').order_by(func.sum(FinanceOperation.summa).desc()).first()

    # Лучший месяц за все время по ПОСТУПЛЕНИЯМ
    best_month_income_query = mysql_session.query(
        extract('year', FinanceOperation.date_added).label('income_year'),
        extract('month', FinanceOperation.date_added).label('income_month'),
        func.sum(FinanceOperation.summa).label('total_income')
    ).filter(
        FinanceOperation.manager_id == manager_id,
        FinanceOperation.status_name == 'Проведено'
    ).group_by('income_year', 'income_month').order_by(func.sum(FinanceOperation.summa).desc()).first()

    # Лучший месяц в выбранном году по ПОСТУПЛЕНИЯМ
    best_month_in_year_income_query = mysql_session.query(
        extract('month', FinanceOperation.date_added).label('income_month'),
        func.sum(FinanceOperation.summa).label('total_income')
    ).filter(
        FinanceOperation.manager_id == manager_id,
        extract('year', FinanceOperation.date_added) == year,
        FinanceOperation.status_name == 'Проведено'
    ).group_by('income_month').order_by(func.sum(FinanceOperation.summa).desc()).first()

    kpis = {
        'best_complex': {
            'name': best_complex_query.complex_name if best_complex_query else None,
            'count': best_complex_query.deal_count if best_complex_query else 0
        },
        'units_by_type': {row.estate_sell_category: row.unit_count for row in units_by_type_query},
        'best_month_in_year': {
            'income': {
                'month': int(best_month_in_year_income_query.income_month) if best_month_in_year_income_query else 0,
                'total': best_month_in_year_income_query.total_income if best_month_in_year_income_query else 0
            }
        },
        'all_time_records': {
            'best_year_income': {
                'year': int(best_year_income_query.income_year) if best_year_income_query else 0,
                'total': best_year_income_query.total_income if best_year_income_query else 0
            },
            'best_month_income': {
                'year': int(best_month_income_query.income_year) if best_month_income_query else 0,
                'month': int(best_month_income_query.income_month) if best_month_income_query else 0,
                'total': best_month_income_query.total_income if best_month_income_query else 0
            }
        }
    }
    return kpis


def get_manager_complex_ranking(manager_id: int):
    """
    Возвращает рейтинг ЖК по количеству сделок и объему ПОСТУПЛЕНИЙ для менеджера.
    """
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    ranking = mysql_session.query(
        EstateHouse.complex_name,
        func.sum(FinanceOperation.summa).label('total_income'),
        func.count(func.distinct(EstateDeal.id)).label('deal_count')
    ).join(EstateSell, EstateHouse.id == EstateSell.house_id) \
     .join(EstateDeal, EstateSell.id == EstateDeal.estate_sell_id) \
     .join(FinanceOperation, EstateSell.id == FinanceOperation.estate_sell_id) \
     .filter(
        EstateDeal.deal_manager_id == manager_id,
        FinanceOperation.manager_id == manager_id, # Дополнительная связка для точности
        FinanceOperation.status_name == "Проведено"
     ) \
     .group_by(EstateHouse.complex_name) \
     .order_by(func.sum(FinanceOperation.summa).desc()) \
     .all()

    return [{"name": r.complex_name, "total_income": r.total_income, "deal_count": r.deal_count} for r in ranking]


def get_complex_hall_of_fame(complex_name: str, start_date_str: str = None, end_date_str: str = None):
    """
    Возвращает рейтинг менеджеров по количеству и объему сделок для ЖК.
    """
    sold_statuses = ["Сделка в работе", "Сделка проведена"]
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    query = mysql_session.query(
        auth_models.SalesManager.full_name,
        func.count(EstateDeal.id).label('deal_count'),
        func.sum(EstateDeal.deal_sum).label('total_volume'),
        func.sum(EstateSell.estate_area).label('total_area')
    ).join(EstateDeal, auth_models.SalesManager.id == EstateDeal.deal_manager_id) \
        .join(EstateSell, EstateDeal.estate_sell_id == EstateSell.id) \
        .join(EstateHouse, EstateSell.house_id == EstateHouse.id) \
        .filter(
        EstateHouse.complex_name == complex_name,
        EstateDeal.deal_status_name.in_(sold_statuses)
    )

    if start_date_str:
        start_date = date.fromisoformat(start_date_str)
        query = query.filter(func.coalesce(EstateDeal.agreement_date, EstateDeal.preliminary_date) >= start_date)
    if end_date_str:
        end_date = date.fromisoformat(end_date_str)
        query = query.filter(func.coalesce(EstateDeal.agreement_date, EstateDeal.preliminary_date) <= end_date)

    ranking = query.group_by(auth_models.SalesManager.id).order_by(func.count(EstateDeal.id).desc()).all()
    return ranking
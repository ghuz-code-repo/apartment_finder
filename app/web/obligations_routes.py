# app/web/obligations_routes.py

from datetime import date  # Добавим date

from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..core.decorators import permission_required, login_required

from app.core.decorators import permission_required
from ..core.db_utils import get_mysql_session
from app.models.estate_models import EstateHouse
from app.services import obligation_service
from app.models.planning_models import PropertyType
obligations_bp = Blueprint('obligations', __name__, template_folder='templates')

@obligations_bp.route('/obligation-control', methods=['GET', 'POST'])
@login_required
@permission_required('view_plan_fact_report') # Или другое подходящее право
def obligation_control():
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО

    # Получаем список проектов для выпадающих списков всегда
    project_names_query = mysql_session.query(EstateHouse.complex_name).distinct().order_by(
        EstateHouse.complex_name).all()  # <--- ИЗМЕНЕНО
    project_names = sorted([name[0] for name in project_names_query if name[0]])

    # Получаем список типов недвижимости
    property_types = [pt.value for pt in PropertyType]

    calculation_result = None
    selected_project_check = request.args.get('project_name_check')
    selected_property_type_check = request.args.get('property_type_check')
    start_date_check = request.args.get('start_date_check')

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_obligation':
            try:
                project = request.form.get('project_name_add')
                property_type = request.form.get('property_type_add')
                amount_str = request.form.get('amount_usd')
                comment = request.form.get('comment_add')

                if not project or not property_type:
                     flash('Необходимо выбрать проект и тип недвижимости.', 'warning')
                elif not amount_str:
                     flash('Необходимо ввести сумму обязательства.', 'warning')
                else:
                    amount_usd = float(amount_str.replace(',', '.'))
                    obligation_service.add_obligation(project, property_type, amount_usd, comment)
                    flash(f'Обязательство для проекта "{project}" ({property_type}) добавлено/обновлено.', 'success')

            except ValueError as e:
                 flash(str(e), 'danger')
            except Exception as e:
                flash(f'Ошибка при добавлении обязательства: {e}', 'danger')
            # Перенаправляем на GET-запрос
            return redirect(url_for('obligations.obligation_control')) # <-- Используем obligations endpoint
        elif action == 'delete_obligation':
             obligation_id = request.form.get('obligation_id')
             if obligation_id:
                 try:
                     success, message = obligation_service.delete_obligation(int(obligation_id))
                     flash(message, 'success' if success else 'danger')
                 except Exception as e:
                     flash(f'Ошибка при удалении: {e}', 'danger')
             else:
                 flash('ID обязательства для удаления не указан.', 'warning')
             return redirect(url_for('obligations.obligation_control')) # <-- Используем obligations endpoint


    elif request.method == 'GET' and selected_project_check and selected_property_type_check and start_date_check:
        # Обработка запроса на расчет - вызов с тремя аргументами
        calculation_result = obligation_service.calculate_required_avg_price(
            selected_project_check,
            selected_property_type_check,
            start_date_check
        )
        if calculation_result and 'error' in calculation_result:
            flash(calculation_result['error'], 'warning')

    # Получаем текущий список обязательств для отображения
    current_obligations = obligation_service.get_all_obligations()

    return render_template(
        'reports/obligation_control.html',
        title="Контроль исполнения обязательств по проектам",
        project_names=project_names,
        property_types=property_types,
        calculation_result=calculation_result,
        current_obligations=current_obligations,
        selected_project_check=selected_project_check,
        selected_property_type_check=selected_property_type_check,
        start_date_check=start_date_check or date.today().strftime('%Y-%m-01')
    )

# Убираем старые маршруты mark_paid, delete_obligation (теперь удаление через POST в obligation_control)
# Старый obligations_report тоже больше не нужен в этой логике
# app/web/complex_calc_routes.py

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from ..core.decorators import permission_required, login_required
from app.services import selection_service, complex_calc_service
from app.core.decorators import permission_required

complex_calc_bp = Blueprint('complex_calc', __name__, template_folder='templates')

@complex_calc_bp.route('/complex-calculations/<int:sell_id>')
@login_required
@permission_required('view_selection')
def show_page(sell_id):
    """Отображает страницу сложных расчетов."""
    card_data = selection_service.get_apartment_card_data(sell_id)
    if not card_data.get('apartment'):
        flash("Объект не найден.", "danger")
        return redirect(url_for('main.selection'))
    return render_template('calc/complex_calculations.html', title="Сложные расчёты", data=card_data)


@complex_calc_bp.route('/calculate-installment', methods=['POST'])
@login_required
@permission_required('view_selection')
def calculate_installment():
    """Обрабатывает AJAX-запрос для расчета стандартной рассрочки."""
    data = request.get_json()
    try:
        sell_id = int(data.get('sell_id'))
        term = int(data.get('term'))
        start_date = data.get('start_date')
        dp_amount = float(data.get('dp_amount', 0.0))
        dp_type = data.get('dp_type', 'uzs')

        additional_discounts = {
            k: float(v) for k, v in data.get('additional_discounts', {}).items() if v and float(v) > 0
        }

        result = complex_calc_service.calculate_installment_plan(
            sell_id=sell_id,
            term_months=term,
            additional_discounts=additional_discounts,
            start_date=start_date,
            dp_amount=dp_amount,
            dp_type=dp_type
        )
        return jsonify(success=True, data=result)
    except (ValueError, TypeError) as e:
        return jsonify(success=False, error=str(e)), 400
    except Exception as e:
        current_app.logger.error(f"Critical error in installment calculation: {e}")
        return jsonify(success=False, error="Произошла внутренняя ошибка на сервере."), 500


@complex_calc_bp.route('/calculate-dp-installment', methods=['POST'])
@login_required
@permission_required('view_selection')
def calculate_dp_installment():
    """Обрабатывает AJAX-запрос для расчета рассрочки на ПВ."""
    data = request.get_json()
    try:
        start_date = data.get('start_date')
        mortgage_type = data.get('mortgage_type', 'standard')

        additional_discounts = {
            k: float(v) for k, v in data.get('additional_discounts', {}).items() if v and float(v) > 0
        }

        result = complex_calc_service.calculate_dp_installment_plan(
            sell_id=int(data.get('sell_id')),
            term_months=int(data.get('term')),
            dp_amount=float(data.get('dp_amount')),
            dp_type=data.get('dp_type'),
            additional_discounts=additional_discounts,
            start_date=start_date,
            mortgage_type=mortgage_type
        )
        return jsonify(success=True, data=result)
    except (ValueError, TypeError) as e:
        return jsonify(success=False, error=str(e)), 400
    except Exception as e:
        current_app.logger.error(f"Critical error in DP installment calculation: {e}")
        return jsonify(success=False, error="Произошла внутренняя ошибка на сервере."), 500

@complex_calc_bp.route('/calculate-zero-mortgage', methods=['POST'])
@login_required
@permission_required('view_selection')
def calculate_zero_mortgage():
    """Обрабатывает AJAX-запрос для расчета ипотеки под 0%."""
    data = request.get_json()
    try:
        additional_discounts = {
            k: float(v) for k, v in data.get('additional_discounts', {}).items() if v and float(v) > 0
        }
        # --- ИЗМЕНЕНИЕ: Получаем тип ипотеки ---
        mortgage_type = data.get('mortgage_type', 'standard')

        result = complex_calc_service.calculate_zero_mortgage(
            sell_id=int(data.get('sell_id')),
            term_months=int(data.get('term_months')),
            dp_percent=int(data.get('dp_percent')),
            additional_discounts=additional_discounts,
            mortgage_type=mortgage_type # --- ИЗМЕНЕНИЕ: Передаем тип ипотеки в сервис
        )
        return jsonify(success=True, data=result)
    except (ValueError, TypeError) as e:
        return jsonify(success=False, error=str(e)), 400
    except Exception as e:
        current_app.logger.error(f"Critical error in zero mortgage calculation: {e}")
        return jsonify(success=False, error="Произошла внутренняя ошибка на сервере."), 500
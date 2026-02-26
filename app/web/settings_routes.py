# app/web/settings_routes.py

import pandas as pd
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file
from flask_login import login_required
from app.core.decorators import permission_required
from app.services import settings_service, report_service
from .forms import CalculatorSettingsForm
from ..core.db_utils import get_planning_session, get_mysql_session, get_default_session
from ..models.estate_models import EstateHouse
from ..models import planning_models
from ..models import auth_models
settings_bp = Blueprint('settings', __name__, template_folder='templates')

@settings_bp.route('/calculator-settings/zero-mortgage/download-template')
@login_required
def download_matrix_template():
    """Отдает сгенерированный шаблон для матрицы кэшбека."""
    return settings_service.generate_zero_mortgage_template()
@settings_bp.route('/download-zero-mortgage-template')
@login_required
@permission_required('manage_settings')
def download_zero_mortgage_template():
    """Отдает пользователю шаблон Excel для матрицы 'Ипотека под 0%'."""
    excel_stream = report_service.generate_zero_mortgage_template_excel()
    return send_file(
        excel_stream,
        download_name='zero_mortgage_matrix_template.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
@settings_bp.route('/calculator-settings', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def manage_settings():
    form = CalculatorSettingsForm()
    settings = settings_service.get_calculator_settings()

    if form.validate_on_submit():
        # Сохранение текстовых полей
        settings_service.update_calculator_settings(request.form)
        flash('Настройки калькуляторов успешно обновлены.', 'success')

        # Обработка загрузки файла
        if form.excel_file.data:
            f = form.excel_file.data
            planning_session = get_planning_session()
            try:
                # 1. Читаем Excel, пропуская первую строку с объединенным заголовком "ПВ"
                df = pd.read_excel(f, header=1)

                # 2. "Разворачиваем" матрицу в плоский список
                id_vars = df.columns[0]  # 'Месяц'
                value_vars = df.columns[1:]  # Колонки с процентами ПВ

                df_unpivoted = df.melt(
                    id_vars=[id_vars],
                    value_vars=value_vars,
                    var_name='dp_percent',
                    value_name='cashback_percent'
                )
                # Переименовываем колонки для соответствия модели
                df_unpivoted.rename(columns={id_vars: 'term_months'}, inplace=True)

                # 3. Очищаем старую матрицу и загружаем новую
                planning_session.query(planning_models.ZeroMortgageMatrix).delete()
                for _, row in df_unpivoted.iterrows():
                    entry = planning_models.ZeroMortgageMatrix(
                        term_months=int(row['term_months']),
                        # Превращаем 0.3, 0.4 обратно в 30, 40
                        dp_percent=int(float(row['dp_percent']) * 100),
                        # Проценты уже должны быть в долях (11% = 0.11), если нет - делим на 100
                        cashback_percent=float(row['cashback_percent']) if row['cashback_percent'] < 1 else float(
                            row['cashback_percent']) / 100.0
                    )
                    planning_session.add(entry)
                planning_session.commit()
                flash('Матрица для "Ипотеки под 0%%" успешно обновлена.', 'success')
            except Exception as e:
                planning_session.rollback()
                flash(f'Ошибка при обработке файла матрицы: {e}', 'danger')

        return redirect(url_for('settings.manage_settings'))

    # Заполняем форму текущими значениями из БД
    form.standard_installment_whitelist.data = settings.standard_installment_whitelist
    form.dp_installment_whitelist.data = settings.dp_installment_whitelist
    form.dp_installment_max_term.data = settings.dp_installment_max_term
    form.time_value_rate_annual.data = settings.time_value_rate_annual
    if hasattr(settings, 'standard_installment_min_dp_percent'):
        form.standard_installment_min_dp_percent.data = settings.standard_installment_min_dp_percent
    if hasattr(settings, 'zero_mortgage_whitelist'):
        form.zero_mortgage_whitelist.data = settings.zero_mortgage_whitelist

    return render_template('settings/calculator_settings.html', title="Настройки калькуляторов", form=form)

@settings_bp.route('/manage-inventory-exclusions', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def manage_inventory_exclusions():
    """Страница для управления исключенными ЖК из сводки по остаткам."""
    if request.method == 'POST':
        complex_name = request.form.get('complex_name')
        if complex_name:
            message, category = settings_service.toggle_complex_exclusion(complex_name)
            flash(message, category)
        return redirect(url_for('settings.manage_inventory_exclusions'))

    # Получаем список всех ЖК и исключенных ЖК
    mysql_session = get_mysql_session()  # <--- ДОБАВЛЕНО
    # Получаем список всех ЖК и исключенных ЖК
    all_complexes = mysql_session.query(EstateHouse.complex_name).distinct().order_by(
        EstateHouse.complex_name).all()  # <--- ИЗМЕНЕНО
    excluded_complexes = settings_service.get_all_excluded_complexes()
    excluded_complexes = settings_service.get_all_excluded_complexes()
    excluded_names = {c.complex_name for c in excluded_complexes}

    return render_template(
        'settings/manage_exclusions.html',
        title="Исключения в сводке по остаткам",
        all_complexes=[c[0] for c in all_complexes],
        excluded_names=excluded_names
    )

@settings_bp.route('/email-recipients', methods=['GET', 'POST'])
@login_required
@permission_required('manage_settings')
def manage_email_recipients():
    """Страница для управления получателями email-уведомлений."""
    default_session = get_default_session() # <--- ДОБАВЛЕНО

    if request.method == 'POST':
        selected_user_ids = request.form.getlist('recipient_ids', type=int)

        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        # Обращаемся к модели через auth_models
        default_session.query(auth_models.EmailRecipient).delete() # <--- ИЗМЕНЕНО

        for user_id in selected_user_ids:
            recipient = auth_models.EmailRecipient(user_id=user_id)
            default_session.add(recipient) # <--- ИЗМЕНЕНО

        default_session.commit() # <--- ИЗМЕНЕНО
        flash('Список получателей уведомлений успешно обновлен.', 'success')
        return redirect(url_for('settings.manage_email_recipients'))

    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    # Обращаемся к моделям через auth_models
    all_users = default_session.query(auth_models.User).order_by(auth_models.User.full_name).all() # <--- ИЗМЕНЕНО
    subscribed_user_ids = {r.user_id for r in default_session.query(auth_models.EmailRecipient).all()} # <--- ИЗМЕНЕНО

    return render_template(
        'settings/manage_recipients.html',
        title="Получатели уведомлений",
        all_users=all_users,
        subscribed_user_ids=subscribed_user_ids
    )
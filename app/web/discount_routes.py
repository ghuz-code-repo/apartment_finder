# app/web/discount_routes.py

import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, send_file, jsonify
from flask_login import login_required
from ..core.db_utils import get_planning_session
from ..core.decorators import permission_required

# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
# Импортируем модуль planning_models вместо классов из discount_models
from ..models import planning_models

from .forms import UploadExcelForm
from ..services import discount_service
from ..services.email_service import send_email
from ..services.discount_service import (
    process_discounts_from_excel,
    generate_discount_template_excel,
    get_discounts_with_summary,
    delete_draft_version,
    activate_version,
    update_discounts_for_version
)

discount_bp = Blueprint('discount', __name__, template_folder='templates')


@discount_bp.route('/discounts')
@login_required
@permission_required('view_discounts')
def discounts_overview():
    # Сервис get_discounts_with_summary сам должен быть обновлен для работы с planning_models
    discounts_data = get_discounts_with_summary()
    return render_template('discounts/discounts.html', title="Система скидок", structured_discounts=discounts_data)


@discount_bp.route('/download-template')
@login_required
@permission_required('manage_discounts')
def download_template():
    excel_data_stream = generate_discount_template_excel()
    return send_file(
        excel_data_stream,
        download_name='discount_template.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@discount_bp.route('/upload-discounts', methods=['GET', 'POST'])
@login_required
@permission_required('manage_discounts')
def upload_discounts():
    form = UploadExcelForm()
    if form.validate_on_submit():
        f = form.excel_file.data
        filename = secure_filename(f.filename)
        upload_folder = os.path.join(current_app.root_path, 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        f.save(file_path)

        try:
            comment = f"Загрузка из файла: {filename}"
            new_version = discount_service.create_blank_version(comment=comment)
            result_message = process_discounts_from_excel(file_path, new_version.id)
            email_data = activate_version(new_version.id)

            if email_data:
                send_email(email_data['subject'], email_data['html_body'])

            flash(f"Файл успешно загружен. Создана и активирована новая версия №{new_version.version_number}. {result_message}", "success")
            return redirect(url_for('discount.versions_index'))
        except Exception as e:
            get_planning_session().rollback()
            flash(f"Произошла ошибка при обработке файла: {e}", "danger")
            return redirect(url_for('discount.upload_discounts'))

    return render_template('discounts/upload.html', title='Загрузка скидок', form=form)


@discount_bp.route('/versions')
@login_required
@permission_required('view_version_history')
def versions_index():
    # Обращаемся к моделям через planning_models
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    versions = planning_session.query(planning_models.DiscountVersion).order_by(
        planning_models.DiscountVersion.version_number.desc()).all()  # <--- ИЗМЕНЕНО
    active_version_obj = next((v for v in versions if v.is_active), None)
    return render_template(
        'discounts/versions.html',
        versions=versions,
        active_version_id=active_version_obj.id if active_version_obj else None,
        latest_version_id=versions[0].id if versions else None,
        title="Версии скидок"
    )


@discount_bp.route('/versions/view/<int:version_id>')
@login_required
@permission_required('view_version_history')
def view_version(version_id):
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    version = planning_session.query(planning_models.DiscountVersion).get_or_404(version_id)  # <--- ИЗМЕНЕНО
    discounts = planning_session.query(planning_models.Discount).filter_by(version_id=version_id).order_by(
        planning_models.Discount.complex_name,
        planning_models.Discount.property_type,
        planning_models.Discount.payment_method
    ).all()
    return render_template(
        'discounts/view_version.html',
        version=version,
        discounts=discounts,
        title=f"Просмотр Версии №{version.version_number}"
    )


@discount_bp.route('/versions/edit/<int:version_id>', methods=['GET', 'POST'])
@login_required
@permission_required('manage_discounts')
def edit_version(version_id):
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    version = planning_session.query(planning_models.DiscountVersion).get_or_404(version_id)  # <--- ИЗМЕНЕНО
    if version.is_active:
        flash('Активные версии нельзя редактировать. Создайте новый черновик.', 'warning')
        return redirect(url_for('discount.versions_index'))

    if request.method == 'POST':
        changes_json = request.form.get('changes_json')
        if not changes_json:
            flash("Нет данных об изменениях для сохранения.", "warning")
            return redirect(url_for('discount.edit_version', version_id=version_id))
        try:
            update_discounts_for_version(version_id, request.form, changes_json)
            flash(f"Изменения в черновике версии №{version.version_number} успешно сохранены.", "success")
        except Exception as e:
            planning_session.rollback()
            flash(f"Произошла критическая ошибка при сохранении: {e}", "danger")
        return redirect(url_for('discount.versions_index'))

    discounts = planning_session.query(planning_models.Discount).filter_by(version_id=version_id).order_by(
        planning_models.Discount.complex_name,
        planning_models.Discount.property_type,
        planning_models.Discount.payment_method
    ).all()
    comments_for_version = planning_session.query(planning_models.ComplexComment).filter_by(version_id=version_id).all()
    complex_comments = {c.complex_name: c.comment for c in comments_for_version}

    return render_template(
        'discounts/edit_version.html',
        version=version,
        discounts=discounts,
        complex_comments=complex_comments,
        title=f"Редактирование Версии №{version.version_number}"
    )


@discount_bp.route('/versions/create-draft', methods=['POST'])
@login_required
@permission_required('manage_discounts')
def create_draft_version():
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    active_version = planning_session.query(planning_models.DiscountVersion).filter_by(
        is_active=True).first()  # <--- ИЗМЕНЕНО
    if not active_version:
        flash('Не найдена активная версия для создания черновика.', 'danger')
        return redirect(url_for('discount.versions_index'))
    try:
        draft_version = discount_service.clone_version_for_editing(active_version)
        flash(f'Создан новый черновик версии №{draft_version.version_number}.', 'success')
        return redirect(url_for('discount.edit_version', version_id=draft_version.id))
    except Exception as e:
        flash(f'Ошибка при создании черновика: {e}', 'danger')
        return redirect(url_for('discount.versions_index'))


@discount_bp.route('/versions/activate/<int:version_id>', methods=['POST'])
@login_required
@permission_required('manage_discounts')
def activate_discount_version(version_id):
    activation_comment = request.form.get('comment')
    if not activation_comment:
        flash("Название (комментарий) для системы скидок не может быть пустым.", "warning")
        return redirect(url_for('discount.versions_index'))
    try:
        email_data = activate_version(version_id, activation_comment=activation_comment)
        if email_data:
            send_email(email_data['subject'], email_data['html_body'])
        planning_session = get_planning_session()
        version = planning_session.query(planning_models.DiscountVersion).get(version_id)  # <--- ИЗМЕНЕНО
        flash(f"Версия №{version.version_number} успешно активирована.", "success")
    except Exception as e:
        flash(f"Ошибка при активации: {e}", "danger")
    return redirect(url_for('discount.versions_index'))


@discount_bp.route('/versions/delete/<int:version_id>', methods=['POST'])
@login_required
@permission_required('manage_discounts')
def delete_version(version_id):
    try:
        delete_draft_version(version_id)
        flash("Черновик версии успешно удален.", "success")
    except (ValueError, PermissionError) as e:
        flash(str(e), "danger")
    except Exception as e:
        flash(f"Произошла неизвестная ошибка при удалении: {e}", "danger")
    return redirect(url_for('discount.versions_index'))


@discount_bp.route('/versions/comment/save', methods=['POST'])
@login_required
@permission_required('manage_discounts')
def save_complex_comment():
    data = request.get_json()
    version_id = data.get('version_id')
    complex_name = data.get('complex_name')
    comment_text = data.get('comment')

    if not all([version_id, complex_name]):
        return jsonify({'success': False, 'error': 'Missing data'}), 400

    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО

    comment = planning_session.query(planning_models.ComplexComment).filter_by(version_id=version_id,
                                                                               complex_name=complex_name).first()  # <--- ИЗМЕНЕНО
    if not comment:
        comment = planning_models.ComplexComment(version_id=version_id, complex_name=complex_name)
        planning_session.add(comment)  # <--- ИЗМЕНЕНО

    comment.comment = comment_text
    planning_session.commit()  # <--- ИЗМЕНЕНО
    return jsonify({'success': True})
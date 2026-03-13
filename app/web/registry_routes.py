# app/web/registry_routes.py

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from ..core.decorators import permission_required, login_required
from app.core.decorators import permission_required
from app.services import registry_service
from app.models.registry_models import RegistryType

registry_bp = Blueprint('registry', __name__, template_folder='templates')


@registry_bp.route('/deals-registry')
@login_required
@permission_required('manage_registry') # Можно создать отдельное право, если нужно
def index():
    # Загружаем данные для всех вкладок сразу или можно через AJAX (сейчас сделаем сразу для простоты)
    data = {
        'vip': registry_service.get_registry_items('vip'),
        'run': registry_service.get_registry_items('run'),
        'gift': registry_service.get_registry_items('gift'),
        'k2': registry_service.get_registry_items('k2'),
    }

    return render_template('registry/index.html', title="Реестр прогонов и спец. сделок", data=data)


@registry_bp.route('/deals-registry/add', methods=['POST'])
@login_required
@permission_required('manage_registry')
def add_deal():
    sell_id = request.form.get('sell_id', type=int)
    reg_type = request.form.get('registry_type')

    # Получаем новые поля (если они не заполнены, будет None)
    k2_sum = request.form.get('k2_sum', type=float)
    crm_sum = request.form.get('crm_sum', type=float)

    if not sell_id or not reg_type:
        flash("Не указан ID объекта или тип реестра", "danger")
        return redirect(url_for('registry.index'))

    # Передаем их в сервис
    success, message = registry_service.add_to_registry(sell_id, reg_type, k2_sum, crm_sum)

    if success:
        flash(message, "success")
    else:
        flash(message, "danger")

    return redirect(url_for('registry.index'))


@registry_bp.route('/deals-registry/delete/<int:id>', methods=['POST'])
@login_required
@permission_required('manage_registry')
def delete_deal(id):
    if registry_service.remove_from_registry(id):
        flash("Запись удалена", "success")
    else:
        flash("Ошибка удаления", "danger")
    return redirect(url_for('registry.index'))
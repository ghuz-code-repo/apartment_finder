# app/web/competitor_routes.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, send_file
from flask_login import login_required
from ..core.decorators import permission_required
from ..services import competitor_service, data_service
from ..models.competitor_models import Competitor

competitor_bp = Blueprint('competitor', __name__)

@competitor_bp.route('/competitors/map')
@login_required
def map_view():
    projects = data_service.get_all_complex_names()
    competitors = Competitor.query.all()
    return render_template('competitors/map.html', competitors=competitors, projects=projects)

@competitor_bp.route('/competitors/import-view')
@login_required
@permission_required('upload_data')
def import_view():
    return render_template('competitors/import.html')

# --- НАШИ ЖК ---
@competitor_bp.route('/competitors/our/export')
@login_required
@permission_required('view_plan_fact_report')
def export_our():
    return send_file(
        competitor_service.export_our_projects(),
        download_name='our_projects_data.xlsx',
        as_attachment=True
    )

@competitor_bp.route('/competitors/our/import', methods=['POST'])
@login_required
@permission_required('upload_data')
def import_our():
    file = request.files.get('file')
    if file:
        competitor_service.import_our_projects(file)
        flash('Данные о наших ЖК обновлены', 'success')
    return redirect(url_for('competitor.map_view'))

# --- КОНКУРЕНТЫ ---
@competitor_bp.route('/competitors/external/export')
@login_required
def export_comp():
    return send_file(
        competitor_service.export_competitors(),
        download_name='competitors_data.xlsx',
        as_attachment=True
    )

@competitor_bp.route('/competitors/external/import', methods=['POST'])
@login_required
def import_comp():
    file = request.files.get('file')
    if file:
        competitor_service.import_competitors(file)
        flash('Данные о конкурентах обновлены', 'success')
    return redirect(url_for('competitor.map_view'))

@competitor_bp.route('/competitors/compare/<int:comp_id>')
@login_required
def compare(comp_id):
    our_project = request.args.get('our_project')
    data = competitor_service.get_comparison(comp_id, our_project)
    if not data:
        return "<div class='alert alert-warning small p-2 mb-0'>Выберите конкурента на карте.</div>"
    return render_template('competitors/_comparison_card.html', data=data)

@competitor_bp.route('/competitors/media/<int:media_id>/delete')
@login_required
def delete_media(media_id):
    media = competitor_service.get_media_by_id(media_id)
    if media:
        comp_id = media.competitor_id
        competitor_service.delete_media(media_id)
        flash('Файл удален', 'success')
        return redirect(url_for('competitor.competitor_profile', comp_id=comp_id))
    return redirect(url_for('competitor.map_view'))

@competitor_bp.route('/competitors/dynamics')
@login_required
def market_dynamics():
    dynamics_data = competitor_service.get_market_dynamics_data()
    return render_template('competitors/dynamics.html', dynamics_data=dynamics_data)

@competitor_bp.route('/competitors/<int:comp_id>')
@login_required
def competitor_profile(comp_id):
    # Получаем данные конкурента по ID через сервис
    comp = competitor_service.get_competitor_by_id(comp_id)

    # Список других конкурентов для выпадающего списка в сравнении
    other_competitors = Competitor.query.filter(Competitor.id != comp_id).all()

    # Список наших проектов для сравнения
    our_projects = data_service.get_all_complex_names()

    return render_template(
        'competitors/profile.html',
        comp=comp,
        other_competitors=other_competitors,
        our_projects=our_projects
    )

@competitor_bp.route('/competitors/<int:comp_id>/update', methods=['POST'])
@login_required
def update_info(comp_id):
    competitor_service.update_competitor_info(comp_id, request.form)
    flash('Информация обновлена', 'success')
    return redirect(url_for('competitor.competitor_profile', comp_id=comp_id))

@competitor_bp.route('/competitors/<int:comp_id>/upload', methods=['POST'])
@login_required
def upload_media(comp_id):
    if 'file' in request.files:
        competitor_service.save_media(comp_id, request.files['file'])
    return redirect(url_for('competitor.competitor_profile', comp_id=comp_id))
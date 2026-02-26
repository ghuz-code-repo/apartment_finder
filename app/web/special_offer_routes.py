# app/web/special_offer_routes.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import login_required
from datetime import date

from app.core.decorators import permission_required
from app.services import special_offer_service
from .forms import MonthlySpecialForm, EditMonthlySpecialForm

# Создаем новый blueprint
special_offer_bp = Blueprint('special_offer', __name__, template_folder='templates')


@special_offer_bp.route('/manage', methods=['GET', 'POST'])
@login_required
@permission_required('manage_specials')
def manage_specials():
    """Страница управления 'Квартирами месяца'."""
    form = MonthlySpecialForm()

    if form.validate_on_submit():
        try:
            special_offer_service.add_special_offer(
                sell_id=form.sell_id.data,
                usp_text=form.usp_text.data,
                extra_discount=form.extra_discount.data,
                image_file=form.floor_plan_image.data
            )
            flash('Новое специальное предложение успешно добавлено!', 'success')
        except Exception as e:
            flash(f'Ошибка при добавлении: {e}', 'danger')

        return redirect(url_for('special_offer.manage_specials'))

    all_offers = special_offer_service.get_all_special_offers()
    today = date.today()

    # Указываем правильный путь к шаблону
    return render_template('special_offers/manage_specials.html',
                           title="Управление Квартирами Месяца",
                           form=form,
                           offers=all_offers,
                           today=today)



@special_offer_bp.route('/edit/<int:special_id>', methods=['GET', 'POST'])
@login_required
@permission_required('manage_specials')
def edit_special(special_id):
    """Страница редактирования спец. предложения."""
    offer = special_offer_service.get_special_offer_details_by_special_id(special_id)
    if not offer:
        abort(404)

    form = EditMonthlySpecialForm()

    if form.validate_on_submit():
        try:
            special_offer_service.update_special_offer(
                special_id=special_id,
                usp_text=form.usp_text.data,
                extra_discount=form.extra_discount.data,
                image_file=form.floor_plan_image.data
            )
            flash('Предложение успешно обновлено!', 'success')
            return redirect(url_for('special_offer.manage_specials'))
        except Exception as e:
            flash(f'Ошибка при обновлении: {e}', 'danger')

    # Заполняем форму текущими данными при GET-запросе
    form.usp_text.data = offer['usp_text']
    form.extra_discount.data = offer['extra_discount']

    # Указываем правильный путь к шаблону
    return render_template('special_offers/edit_special.html',
                           title=f"Редактирование предложения ID {offer['sell_id']}",
                           form=form,
                           offer=offer)


@special_offer_bp.route('/delete/<int:special_id>', methods=['POST'])
@login_required
@permission_required('manage_specials')
def delete_special(special_id):
    """Удаляет спец. предложение."""
    try:
        special_offer_service.delete_special_offer(special_id)
        flash('Специальное предложение успешно удалено.', 'success')
    except Exception as e:
        flash(f'Ошибка при удалении: {e}', 'danger')
    return redirect(url_for('special_offer.manage_specials'))


@special_offer_bp.route('/extend/<int:special_id>', methods=['POST'])
@login_required
@permission_required('manage_specials')
def extend_special(special_id):
    """Продлевает срок действия предложения."""
    try:
        special_offer_service.extend_special_offer(special_id)
        flash('Срок предложения успешно продлен!', 'success')
    except Exception as e:
        flash(f'Ошибка при продлении: {e}', 'danger')
    return redirect(url_for('special_offer.manage_specials'))
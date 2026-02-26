# auth_routes.py

from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user

from ..core.decorators import permission_required
from ..core.db_utils import get_default_session
from .forms import CreateUserForm, ChangePasswordForm, RoleForm

# --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
# Импортируем сам модуль auth_models вместо отдельных классов из user_models
from ..models import auth_models

auth_bp = Blueprint('auth', __name__, template_folder='templates')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Обращаемся к модели User через auth_models
        default_session = get_default_session()  # <--- ДОБАВЛЕНО
        user = default_session.query(auth_models.User).filter_by(username=username).first()  # <--- ИЗМЕНЕНО
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
        else:
            flash('Неверный логин или пароль.', 'danger')

    return render_template('auth/login.html', title='Вход в систему')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы успешно вышли из системы.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/users', methods=['GET', 'POST'])
@login_required
@permission_required('manage_users')
def user_management():
    form = CreateUserForm()
    # Загружаем роли из auth_models
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    form.role.choices = [(r.id, r.name) for r in
                         default_session.query(auth_models.Role).order_by('name').all()]  # <--- ИЗМЕНЕНО

    if form.validate_on_submit():
        role_obj = default_session.query(auth_models.Role).get(form.role.data)
        user = auth_models.User(
            username=form.username.data,
            role=role_obj,
            full_name=form.full_name.data,
            email=form.email.data,
            phone_number=form.phone_number.data
        )
        user.set_password(form.password.data)
        default_session.add(user)  # <--- ИЗМЕНЕНО
        default_session.commit()
        flash(f'Пользователь {user.username} успешно создан.', 'success')
        return redirect(url_for('auth.user_management'))

    users = default_session.query(auth_models.User).order_by(auth_models.User.id).all()
    return render_template('auth/user_management.html', title="Управление пользователями", users=users, form=form)


@auth_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@permission_required('manage_users')
def delete_user(user_id):
    if user_id == current_user.id:
        flash('Вы не можете удалить свою учетную запись.', 'danger')
        return redirect(url_for('auth.user_management'))

    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    user_to_delete = default_session.query(auth_models.User).get_or_404(user_id)  # <--- ИЗМЕНЕНО
    default_session.delete(user_to_delete)  # <--- ИЗМЕНЕНО
    default_session.commit()
    flash(f'Пользователь {user_to_delete.username} удален.', 'success')
    return redirect(url_for('auth.user_management'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('Введен неверный текущий пароль.', 'danger')
        else:
            default_session = get_default_session()  # <--- ДОБАВЛЕНО
            current_user.set_password(form.new_password.data)
            default_session.commit()
            flash('Ваш пароль успешно изменен.', 'success')
            return redirect(url_for('main.selection'))

    return render_template('auth/change_password.html', title="Смена пароля", form=form)


@auth_bp.route('/roles')
@login_required
@permission_required('manage_users')
def manage_roles():
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    roles = default_session.query(auth_models.Role).order_by(auth_models.Role.name).all()  # <--- ИЗМЕНЕНО
    return render_template('auth/manage_roles.html', title="Управление ролями", roles=roles)


@auth_bp.route('/role/edit/<int:role_id>', methods=['GET', 'POST'])
@auth_bp.route('/role/new', methods=['GET', 'POST'], defaults={'role_id': None})
@login_required
@permission_required('manage_users')
def role_form(role_id):
    default_session = get_default_session()
    if role_id:
        role = default_session.query(auth_models.Role).get_or_404(role_id)
        form = RoleForm(obj=role)
        title = f"Редактирование роли: {role.name}"
    else:
        role = auth_models.Role()
        form = RoleForm()
        title = "Создание новой роли"

    form.permissions.choices = [(p.id, p.description) for p in default_session.query(auth_models.Permission).order_by('description').all()]

    if form.validate_on_submit():
        role.name = form.name.data
        selected_permissions = default_session.query(auth_models.Permission).filter(auth_models.Permission.id.in_(form.permissions.data)).all()
        role.permissions = selected_permissions

        if not role_id:
            default_session.add(role)

        default_session.commit()
        flash(f"Роль '{role.name}' успешно сохранена.", "success")
        return redirect(url_for('auth.manage_roles'))

    all_permissions = default_session.query(auth_models.Permission).order_by('description').all()
    selected_permission_ids = {p.id for p in role.permissions}

    return render_template(
        'auth/role_form.html',
        title=title,
        form=form,
        all_permissions=all_permissions,
        selected_permission_ids=selected_permission_ids
    )


@auth_bp.route('/role/delete/<int:role_id>', methods=['POST'])
@login_required
@permission_required('manage_users')
def delete_role(role_id):
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    role = default_session.query(auth_models.Role).get_or_404(role_id)
    if role.users.count() > 0:
        flash(f"Нельзя удалить роль '{role.name}', так как она присвоена пользователям.", 'danger')
        return redirect(url_for('auth.manage_roles'))

    default_session.delete(role)  # <--- ИЗМЕНЕНО
    default_session.commit()
    flash(f"Роль '{role.name}' успешно удалена.", 'success')
    return redirect(url_for('auth.manage_roles'))
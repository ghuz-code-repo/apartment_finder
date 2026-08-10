# auth_routes.py
# Gateway-only auth: all authentication is handled by the gateway.
# This blueprint only provides redirect stubs so old URLs don't break.

from flask import Blueprint, redirect, abort

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Redirect to gateway login."""
    return redirect('/login')


@auth_bp.route('/logout')
def logout():
    """Redirect to gateway logout."""
    return redirect('/logout')


@auth_bp.route('/users', methods=['GET', 'POST'])
def user_management():
    """Redirect to gateway admin panel."""
    return redirect('/admin')


@auth_bp.route('/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    """Not available — managed by gateway."""
    abort(404)


@auth_bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    """Redirect to gateway profile."""
    return redirect('/profile')


@auth_bp.route('/roles')
def manage_roles():
    """Redirect to gateway admin panel."""
    return redirect('/admin')


@auth_bp.route('/role/edit/<int:role_id>', methods=['GET', 'POST'])
@auth_bp.route('/role/new', methods=['GET', 'POST'], defaults={'role_id': None})
def role_form(role_id):
    """Not available — managed by gateway."""
    abort(404)


@auth_bp.route('/role/delete/<int:role_id>', methods=['POST'])
def delete_role(role_id):
    """Not available — managed by gateway."""
    abort(404)
# app/models/auth_models.py

from flask_login import UserMixin, AnonymousUserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.core.extensions import db
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm import joinedload, selectinload

class Permission:
    MANAGE_USERS = 0x01
    MANAGE_SETTINGS = 0x02
    MANAGE_DISCOUNTS = 0x04
    UPLOAD_DATA = 0x08
    VIEW_REPORTS = 0x10
    MANAGE_CANCELLATIONS = 0x20
    MANAGE_REGISTRY = 0x40

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    permissions = db.relationship(
        'Permission',
        secondary='role_permissions',
        back_populates='roles',
        lazy='joined'
    )
    users = db.relationship('User', back_populates='role')


class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    description = db.Column(db.String(255))
    roles = db.relationship('Role', secondary='role_permissions', back_populates='permissions')


role_permissions = db.Table(
    'role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    # --- ЭТО ЛОКАЛЬНЫЙ ПОЛЬЗОВАТЕЛЬ ДЛЯ ЛОГИНА (main_app.db) ---
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    full_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), index=True, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(256))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    role = db.relationship('Role', back_populates='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def can(self, perm_name):
        if self.role is None:
            return False
        # Если администратор — разрешаем всё автоматически
        if self.is_admin:
            return True
        # Проверка прав с приведением к нижнему регистру для избежания ошибок
        return any(p.name.lower() == perm_name.lower() for p in self.role.permissions)

    @property
    def is_admin(self):
        return self.role and self.role.name == 'ADMIN'


class AnonymousUser(AnonymousUserMixin):
    def can(self, perm_name):
        return False

    @property
    def is_admin(self):
        return False


class SalesManager(db.Model):
    # --- ЭТО МЕНЕДЖЕР ИЗ MYSQL (mysql_source) ---
    __bind_key__ = 'mysql_source'
    __tablename__ = 'users'  # <-- Указываем на таблицу 'users' в MySQL

    id = db.Column(db.Integer, primary_key=True)

    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
    # Мы говорим SQLAlchemy:
    # "Свойство 'full_name' в Python соответствует столбцу 'users_name' в MySQL"
    full_name = db.Column('users_name', db.String(255), nullable=False)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

    post_title = db.Column(db.String(255), nullable=True)

    # Связь с ManagerSalesPlan (в planning_models)
    plans = db.relationship(
        'app.models.planning_models.ManagerSalesPlan',
        primaryjoin='SalesManager.id == foreign(app.models.planning_models.ManagerSalesPlan.manager_id)',
        back_populates='manager'
    )
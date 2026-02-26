# forms.py

from datetime import date
from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, FileField, SelectField,
                     SelectMultipleField, TextAreaField, IntegerField, FloatField)
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError, Email, NumberRange, Optional
from wtforms.widgets import CheckboxInput
from ..models import auth_models
from flask_babel import lazy_gettext as _
from wtforms import StringField, SubmitField, FileField
from flask_wtf.file import FileAllowed
class UploadExcelForm(FlaskForm):
    """Форма для загрузки Excel файла."""
    excel_file = FileField(
        _('Выберите Excel-файл со скидками'),
        validators=[DataRequired(message=_("Необходимо выбрать файл."))]
    )
    submit = SubmitField(_('Загрузить'))

class UploadZeroMortgageMatrixForm(FlaskForm):
    """Форма для загрузки Excel файла с матрицей для ипотеки 0%."""
    excel_file = FileField(
        _('Выберите Excel-файл с матрицей'),
        validators=[DataRequired(message=_("Необходимо выбрать файл."))]
    )
    submit = SubmitField(_('Загрузить матрицу'))
class CreateUserForm(FlaskForm):
    """Форма создания пользователя."""
    username = StringField(_('Имя пользователя'), validators=[DataRequired(), Length(min=4, max=64)])
    full_name = StringField(_('ФИО'), validators=[DataRequired()])
    email = StringField(_('Email'), validators=[DataRequired(), Email(message=_("Некорректный email адрес."))])
    phone_number = StringField(_('Номер телефона (опционально)'))
    role = SelectField(_('Роль'), coerce=int, validators=[DataRequired()])
    password = PasswordField(_('Пароль'), validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(_('Подтвердите пароль'), validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField(_('Создать пользователя'))

    def validate_username(self, username):
        """Проверка, что имя пользователя еще не занято."""
        if auth_models.User.query.filter_by(username=username.data).first():
            raise ValidationError(_('Это имя пользователя уже занято.'))

    def validate_email(self, email):
        """Проверка, что email еще не занят."""
        if auth_models.User.query.filter_by(email=email.data).first():
            raise ValidationError(_('Этот email уже зарегистрирован.'))


class ChangePasswordForm(FlaskForm):
    """Форма смены пароля."""
    current_password = PasswordField(_('Текущий пароль'), validators=[DataRequired()])
    new_password = PasswordField(_('Новый пароль'), validators=[DataRequired(), Length(min=6)])
    confirm_new_password = PasswordField(_('Подтвердите новый пароль'), validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField(_('Сменить пароль'))


class UploadPlanForm(FlaskForm):
    """Форма для загрузки Excel файла с планами."""
    excel_file = FileField(
        _('Выберите Excel-файл с планами'),
        validators=[DataRequired(message=_("Необходимо выбрать файл."))]
    )
    year = IntegerField(_('Год'), validators=[DataRequired()], default=date.today().year)
    month = SelectField(_('Месяц'), coerce=int, choices=[(i, f'{i:02d}') for i in range(1, 13)],
                        default=date.today().month)
    submit = SubmitField(_('Загрузить план'))


class CalculatorSettingsForm(FlaskForm):
    """Форма для настроек калькуляторов."""
    standard_installment_whitelist = TextAreaField(_('ID квартир для обычной рассрочки (через запятую)'))
    dp_installment_whitelist = TextAreaField(_('ID квартир для рассрочки на ПВ (через запятую)'))
    dp_installment_max_term = IntegerField(_('Макс. срок рассрочки на ПВ (мес)'),
                                           validators=[DataRequired(), NumberRange(min=1, max=36)])
    time_value_rate_annual = FloatField(_('Годовая ставка для коэфф. (%)'),
                                        validators=[DataRequired(), NumberRange(min=0)])
    standard_installment_min_dp_percent = FloatField(
        _('Мин. ПВ для стандартной рассрочки (%)'),
        validators=[DataRequired(message=_("Это поле обязательно.")), NumberRange(min=0, max=100)],
        default=15.0
    )
    submit = SubmitField(_('Сохранить настройки'))


class CalculatorSettingsForm(FlaskForm):
    """Форма для настроек калькуляторов."""
    standard_installment_whitelist = TextAreaField(_('ID квартир для обычной рассрочки (через запятую)'))
    dp_installment_whitelist = TextAreaField(_('ID квартир для рассрочки на ПВ (через запятую)'))
    dp_installment_max_term = IntegerField(_('Макс. срок рассрочки на ПВ (мес)'),
                                           validators=[DataRequired(), NumberRange(min=1, max=36)])
    time_value_rate_annual = FloatField(_('Годовая ставка для коэфф. (%)'),
                                        validators=[DataRequired(), NumberRange(min=0)])
    standard_installment_min_dp_percent = FloatField(
        _('Мин. ПВ для стандартной рассрочки (%%)'),
        validators=[DataRequired(message=_("Это поле обязательно.")), NumberRange(min=0, max=100)],
        default=15.0
    )
    # --- НОВЫЕ ПОЛЯ ---
    zero_mortgage_whitelist = TextAreaField(_('ID квартир для "Ипотеки под 0%" (через запятую)'))
    excel_file = FileField(_('Загрузить новую матрицу для "Ипотеки под 0%" (Excel)'), validators=[Optional()])

    submit = SubmitField(_('Сохранить настройки'))
class UploadManagerPlanForm(FlaskForm):
    """Форма для загрузки Excel файла с планами менеджеров."""
    excel_file = FileField(
        _('Выберите Excel-файл с планами'),
        validators=[DataRequired(message=_("Необходимо выбрать файл."))]
    )
    submit = SubmitField(_('Загрузить планы'))


class RoleForm(FlaskForm):
    """Форма для создания и редактирования ролей."""
    name = StringField(_('Название роли'), validators=[DataRequired(), Length(min=2, max=80)])
    permissions = SelectMultipleField(
        _('Разрешения для роли'),
        coerce=int,
        widget=CheckboxInput()
    )
    submit = SubmitField(_('Сохранить'))


class MonthlySpecialForm(FlaskForm):
    """Форма для добавления/редактирования 'Квартиры месяца'."""
    sell_id = IntegerField(_('ID Квартиры (из estate_sells)'), validators=[DataRequired(message=_("ID квартиры обязателен."))])
    usp_text = TextAreaField(_('УТП (Уникальное Торговое Предложение)'), validators=[DataRequired(message=_("Укажите УТП."))])
    extra_discount = FloatField(_('Дополнительная скидка (%)'), validators=[DataRequired(), NumberRange(min=0, max=50)])
    floor_plan_image = FileField(_('Файл с планировкой (png, jpg, svg, webp)'), validators=[DataRequired(message=_("Загрузите планировку."))])
    submit = SubmitField(_('Добавить предложение'))


class EditMonthlySpecialForm(FlaskForm):
    """Форма для РЕДАКТИРОВАНИЯ 'Квартиры месяца'."""
    usp_text = TextAreaField(_('УТП (Уникальное Торговое Предложение)'), validators=[DataRequired(message=_("Укажите УТП."))])
    extra_discount = FloatField(_('Дополнительная скидка (%)'), validators=[DataRequired(), NumberRange(min=0, max=50)])
    floor_plan_image = FileField(_('Загрузить НОВУЮ планировку (необязательно)'), validators=[Optional()])
    submit = SubmitField(_('Сохранить изменения'))
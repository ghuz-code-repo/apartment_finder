# app/services/settings_service.py

from ..core.db_utils import get_planning_session, get_default_session
import pandas as pd
import io
from flask import make_response
import io
from flask import make_response
# --- ИЗМЕНЕНИЯ ЗДЕСЬ: Обновляем импорты ---
from ..models import planning_models
from ..models.exclusion_models import ExcludedComplex
import pandas as pd
from app.models.finance_models import ZeroMortgageMatrix
from app.models.planning_models import CalculatorSettings
import json
from datetime import datetime
def get_calculator_settings():
    """
    Получает настройки калькуляторов. Если их нет, создает по умолчанию.
    Использует паттерн "Синглтон", всегда работая с записью id=1.
    """
    # Используем planning_models.CalculatorSettings
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    settings = planning_session.query(planning_models.CalculatorSettings).get(1)  # <--- ИЗМЕНЕНО
    if not settings:
        settings = planning_models.CalculatorSettings(id=1)
        planning_session.add(settings)  # <--- ИЗМЕНЕНО
        planning_session.commit()  # <--- ИЗМЕНЕНО
    return settings


def get_all_excluded_complexes():
    """Возвращает список всех исключенных ЖК."""
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    return default_session.query(ExcludedComplex).order_by(ExcludedComplex.complex_name).all()  # <--- ИЗМЕНЕНО


def toggle_complex_exclusion(complex_name: str):
    """
    Добавляет ЖК в список исключений, если его там нет,
    или удаляет, если он там уже есть.
    """
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    existing = default_session.query(ExcludedComplex).filter_by(complex_name=complex_name).first()  # <--- ИЗМЕНЕНО
    if existing:
        default_session.delete(existing)
        message = f"Проект '{complex_name}' был удален из списка исключений."
        category = "success"
    else:
        new_exclusion = ExcludedComplex(complex_name=complex_name)
        default_session.add(new_exclusion)
        message = f"Проект '{complex_name}' был добавлен в список исключений."
        category = "info"

    default_session.commit()
    return message, category


def update_calculator_settings(form_data):
    """Обновляет настройки калькуляторов из данных формы."""
    settings = get_calculator_settings()

    settings.standard_installment_whitelist = form_data.get('standard_installment_whitelist', '')
    settings.dp_installment_whitelist = form_data.get('dp_installment_whitelist', '')
    settings.dp_installment_max_term = int(form_data.get('dp_installment_max_term', 6))
    settings.time_value_rate_annual = float(form_data.get('time_value_rate_annual', 16.5))
    settings.standard_installment_min_dp_percent = float(form_data.get('standard_installment_min_dp_percent', 15.0))
    settings.zero_mortgage_whitelist = form_data.get('zero_mortgage_whitelist', '')
    planning_session = get_planning_session()
    planning_session.commit()
def save_zero_mortgage_matrix(file_storage):
    """
    Parses a CSV file with mortgage matrix and saves it to the database.
    Deactivates previous active matrices.
    """
    default_session = get_default_session()
    try:
        df = pd.read_csv(file_storage, index_col=0)
        # Преобразуем столбцы 'ПВ2', 'ПВ3' и т.д. в '30', '40'
        # Предполагаем, что ПВ2 = 30%, ПВ3 = 40% и т.д. Если логика иная, скорректируйте формулу.
        df.columns = [str(int(col.replace('ПВ', '')) * 10) for col in df.columns]
        matrix_json = df.to_dict(orient='index')

        default_session.query(ZeroMortgageMatrix).filter_by(is_active=True).update({"is_active": False})

        matrix_name = f"matrix_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        new_matrix = ZeroMortgageMatrix(name=matrix_name, data=matrix_json, is_active=True)
        default_session.add(new_matrix)  # <--- ИЗМЕНЕНО
        default_session.commit()  # <--- ИЗМЕНЕНО
        return True, "Матрица успешно обновлена."
    except Exception as e:
        default_session.rollback()  # <--- ИЗМЕНЕНО
        return False, f"Ошибка при обработке файла: {e}"


def generate_zero_mortgage_template():
    """
    Генерирует шаблон матрицы кэшбека в виде Excel (.xlsx) файла "на лету".
    """
    # Данные для шаблона остаются теми же
    data = {
        'Срок': [18, 24, 30, 36, 42, 48, 54, 60],
        '30': [0.16, 0.21, 0.26, 0.31, 0.36, 0.41, 0.45, 0.50],
        '40': [0.14, 0.18, 0.22, 0.26, 0.31, 0.35, 0.39, 0.43],
        '50': [0.12, 0.15, 0.19, 0.22, 0.26, 0.29, 0.33, 0.36],
        '60': [0.09, 0.12, 0.15, 0.18, 0.21, 0.23, 0.26, 0.29]
    }
    df = pd.DataFrame(data)

    # Создаем Excel-файл в бинарном потоке в памяти
    output = io.BytesIO()
    df.to_excel(output, index=False, sheet_name='Template')
    output.seek(0)

    # Формируем HTTP-ответ с правильными заголовками для .xlsx
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=matrix_template.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return response


def get_active_zero_mortgage_matrix():
    """ Fetches the active zero mortgage matrix data. """
    default_session = get_default_session()  # <--- ДОБАВЛЕНО
    matrix = default_session.query(ZeroMortgageMatrix).filter_by(is_active=True).first()  # <--- ИЗМЕНЕНО
    return matrix.data if matrix else None


def save_zero_mortgage_projects(project_ids_str):
    """ Saves the list of applicable project IDs for zero mortgage into CalculatorSettings. """
    # Используем существующую функцию для получения настроек
    settings = get_calculator_settings()
    planning_session = get_planning_session()  # <--- ДОБАВЛЕНО
    if not settings:
        settings = CalculatorSettings()
        planning_session.add(settings)

    try:
        project_ids = [int(p_id.strip()) for p_id in project_ids_str.split(',') if p_id.strip()]
        settings.zero_mortgage_project_ids = json.dumps(project_ids)
        planning_session.commit()
        return True, "Список объектов для 'Ипотеки под ноль' обновлен."
    except ValueError:
        return False, "ID объектов должны быть целыми числами."
    except Exception as e:
        planning_session.rollback()
        return False, f"Произошла ошибка при сохранении ID объектов: {e}"


def get_zero_mortgage_projects():
    """ Gets the list of applicable project IDs for zero mortgage from CalculatorSettings. """
    settings = get_calculator_settings()
    if settings and settings.zero_mortgage_project_ids:
        try:
            return json.loads(settings.zero_mortgage_project_ids)
        except json.JSONDecodeError:
            return []
    return []

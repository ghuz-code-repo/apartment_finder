# app/web/ai_routes.py
from flask import Blueprint, render_template, request, jsonify
from app.services.ai_forecast_service import AIForecastService

# Эта переменная ДОЛЖНА называться ai_bp
ai_bp = Blueprint('ai', __name__, url_prefix='/ai')

@ai_bp.route('/forecast', methods=['GET'])
def forecast_page():
    return render_template('ai/forecast.html')


@ai_bp.route('/api/train', methods=['POST'])
def train_model_api():
    result = AIForecastService.train_with_validation()

    if isinstance(result, str):
        # Если вернулась строка (ошибка данных), отправляем её в поле message
        return jsonify({
            "status": "error",
            "message": result,
            "mae": "н/д"
        }), 400

    return jsonify({
        "status": "success",
        "mae": result
    })

@ai_bp.route('/api/get_forecast', methods=['POST'])
def get_forecast_api():
    month = request.json.get('month')
    if not month:
        return jsonify({"error": "Month is required"}), 400
    data = AIForecastService.predict_for_month(int(month))
    return jsonify(data)
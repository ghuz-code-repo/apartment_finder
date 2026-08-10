# app/core/auth_utils.py
import hmac
import hashlib
import urllib.parse
from flask import current_app
from app.core.config import Config


def verify_telegram_data(init_data: str) -> bool:
    """
    Проверяет подпись данных, пришедших от Telegram Mini App.
    """
    if not init_data:
        return False

    try:
        # Парсим строку запроса
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        hash_value = parsed_data.pop('hash', None)
        if not hash_value:
            return False

        # Сортируем ключи и собираем строку для проверки
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(parsed_data.items())])

        # Вычисляем секретный ключ на основе токена бота
        secret_key = hmac.new(b"WebAppData", Config.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        # Вычисляем проверочный хеш
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        return calculated_hash == hash_value
    except Exception as e:
        current_app.logger.error(f"Error verifying Telegram data: {e}")
        return False
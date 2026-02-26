# app/core/config.py

import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-very-secret-key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TELEGRAM_BOT_TOKEN = '8511926898:AAHujmgGC9vgm23lcu82HEUjtFdwvr91va8'

    # Попробуйте сначала ID из вашего бота-помощника
    TELEGRAM_CHANNEL_ID = -5055698551
    # URI    для подключения к исходной базе данных MySQL (для импорта)
    # Используйте переменные окружения для безопасности
    SOURCE_MYSQL_URI = (
        f"mysql+pymysql://"
        f"macro_bi_cmp_528:p[8qG^]Qf3v[qr*1"  # <-- Замените на ваши данные
        f"@172.16.0.199:9906"  # <-- Правильный IP и порт
        f"/macro_bi_cmp_528"  # <-- Замените на ваши данные
    )

    # Настройки для отправки Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'mail.gh.uz')
    MAIL_PORT = int(os.environ.get('MAIL_SERVER_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('SEND_FROM_EMAIL', 'robot@gh.uz')
    MAIL_PASSWORD = os.environ.get('SEND_FROM_EMAIL_PASSWORD', 'ABwHRMp1')
    MAIL_RECIPIENTS = ['d.plakhotnyi@gh.uz']
    USD_TO_UZS_RATE = 13050.0


# --- ИЗМЕНЕНИЯ НУЖНО ВНЕСТИ ЗДЕСЬ ---
class DevelopmentConfig(Config):
    DEBUG = True

    # Основная база данных
    SQLALCHEMY_DATABASE_URI = os.environ.get('MAIN_DATABASE_URL') or 'sqlite:///main_app.db'

    # Оставляем 'planning_db' и добавляем 'mysql_source'
    SQLALCHEMY_BINDS = {
        'planning_db': os.environ.get('PLANNING_DATABASE_URL') or 'sqlite:///planning.db',
        'mysql_source': Config.SOURCE_MYSQL_URI  # Прямое подключение к MySQL
    }
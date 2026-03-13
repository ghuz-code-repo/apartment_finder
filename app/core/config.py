# app/core/config.py

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'a-very-secret-key')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHANNEL_ID = int(os.environ.get('TELEGRAM_CHANNEL_ID', '0'))
    SOURCE_MYSQL_URI = os.environ.get('SOURCE_MYSQL_URI', '')

    # Настройки для отправки Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'mail.gh.uz')
    MAIL_PORT = int(os.environ.get('MAIL_SERVER_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('SEND_FROM_EMAIL', 'robot@gh.uz')
    MAIL_PASSWORD = os.environ.get('SEND_FROM_EMAIL_PASSWORD', '')
    MAIL_RECIPIENTS = ['d.plakhotnyi@gh.uz']
    USD_TO_UZS_RATE = 13050.0


# --- ИЗМЕНЕНИЯ НУЖНО ВНЕСТИ ЗДЕСЬ ---
class DevelopmentConfig(Config):
    DEBUG = True

    # Основная база данных (абсолютный путь в instance/)
    _basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    _instance_path = os.path.join(_basedir, 'instance')

    SQLALCHEMY_DATABASE_URI = os.environ.get('MAIN_DATABASE_URL') or \
        'sqlite:///' + os.path.join(_instance_path, 'main_app.db')

    # Оставляем 'planning_db' и добавляем 'mysql_source'
    SQLALCHEMY_BINDS = {
        'planning_db': os.environ.get('PLANNING_DATABASE_URL') or \
            'sqlite:///' + os.path.join(_instance_path, 'planning.db'),
        'mysql_source': Config.SOURCE_MYSQL_URI  # Прямое подключение к MySQL
    }
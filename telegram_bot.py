# telegram_bot.py
"""Воркер бота-напоминалки о дебиторке.

Отдельный процесс рядом со scheduler.py: опрашивает Telegram методом
getUpdates и раз в день рассылает менеджерам их дебиторку. Long polling выбран
вместо вебхука сознательно — не нужен ни публичный HTTPS-адрес, ни исключение
в авторизации шлюза.

Запуск: python telegram_bot.py
"""

import os
import sys
import time
from datetime import datetime

import requests

sys.path.append(os.getcwd())

from app import create_app
from app.core.config import DevelopmentConfig
from app.services import telegram_reminder_service as reminder

# Сколько Telegram держит соединение, если новых сообщений нет.
LONG_POLL_TIMEOUT = 25
# Пауза после сетевой ошибки, чтобы не молотить API в цикле.
ERROR_SLEEP = 15

app = create_app(DevelopmentConfig)


def api_url(method):
    token = app.config.get('TELEGRAM_BOT_TOKEN')
    return f'https://api.telegram.org/bot{token}/{method}'


def fetch_updates(offset):
    """Забирает апдейты. Возвращает (список, новый offset)."""
    response = requests.get(
        api_url('getUpdates'),
        params={'offset': offset, 'timeout': LONG_POLL_TIMEOUT},
        timeout=LONG_POLL_TIMEOUT + 10,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get('ok'):
        print(f'[БОТ] Telegram вернул ошибку: {payload}')
        return [], offset

    updates = payload.get('result', [])
    if updates:
        offset = updates[-1]['update_id'] + 1
    return updates, offset


def process_updates(updates):
    """Отвечает на команды. Вся логика — в сервисе, здесь только ввод-вывод."""
    for update in updates:
        try:
            answer = reminder.handle_update(update)
        except Exception as e:  # noqa: BLE001 — один кривой апдейт не должен ронять воркер
            print(f'[БОТ] Ошибка обработки апдейта: {e}')
            continue

        if not answer:
            continue

        chat_id = ((update.get('message') or {}).get('chat') or {}).get('id')
        reminder.send_message(chat_id, answer)


def run():
    token = app.config.get('TELEGRAM_BOT_TOKEN')
    if not token:
        print('[БОТ] TELEGRAM_BOT_TOKEN не задан — воркер не запускается.')
        return

    print('--- [БОТ-НАПОМИНАЛКА ЗАПУЩЕН] ---')
    offset = None

    while True:
        try:
            with app.app_context():
                updates, offset = fetch_updates(offset)
                if updates:
                    process_updates(updates)

                # Рассылку проверяем на каждом круге: она сама смотрит, чей это
                # час и не отправляли ли уже сегодня.
                result = reminder.send_due_reminders()
                if result['sent']:
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Напоминаний отправлено: {result['sent']}")

        except requests.RequestException as e:
            print(f'[БОТ] Сеть недоступна: {e}. Пауза {ERROR_SLEEP} с.')
            time.sleep(ERROR_SLEEP)
        except Exception as e:  # noqa: BLE001 — воркер должен пережить любую ошибку круга
            print(f'[БОТ] Непредвиденная ошибка: {e}. Пауза {ERROR_SLEEP} с.')
            time.sleep(ERROR_SLEEP)


if __name__ == '__main__':
    run()

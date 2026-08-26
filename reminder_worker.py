"""Рассылка напоминаний о дебиторке.

Отдельный процесс, а не часть scheduler.py: тот вместе с рассылкой тянет
инкрементную синхронизацию с MySQL и блокировку базы, а напоминаниям ни то ни
другое не нужно. В деплое поднимается вторым сервисом compose из того же образа.

Запуск:
    python reminder_worker.py           # цикл, проверка каждые 5 минут
    python reminder_worker.py --once    # один проход и выход (для cron)

Кому именно пора, решает сервис: он смотрит интервал подписки и время прошлой
отправки, поэтому будить процесс можно чаще, чем нужно самим напоминаниям.
"""

import os
import sys
import time
from datetime import datetime

sys.path.append(os.getcwd())

from app import create_app
from app.services import debt_reminder_service

# Как часто просыпаемся. Достаточно мелко для часового режима и не создаёт
# заметной нагрузки: пустой проход — это один запрос к таблице подписок.
CHECK_INTERVAL_SECONDS = int(os.environ.get('REMINDER_CHECK_INTERVAL', '300'))


def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_once(app):
    """Один проход рассылки. Возвращает счётчики сервиса."""
    with app.app_context():
        result = debt_reminder_service.send_due_reminders()

    if result['sent'] or result['skipped']:
        log(f"Напоминания: отправлено={result['sent']}, "
            f"без долгов={result['quiet']}, ошибок={result['skipped']}")
    return result


def main():
    app = create_app()
    once = '--once' in sys.argv

    if once:
        run_once(app)
        return

    log(f"Воркер напоминаний запущен, проверка каждые {CHECK_INTERVAL_SECONDS} с.")
    while True:
        try:
            run_once(app)
        except Exception as e:
            # Падение одного круга не должно останавливать рассылку навсегда.
            log(f"Ошибка рассылки: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()

"""Страж встреч: задача-встреча при переходе в «Сделку в работе».

Команды:
    python meeting_guard.py types           # типы задач CRM — узнать id «Встреча в офисе»
    python meeting_guard.py check 1234567   # разобрать одну заявку, ничего не создавая
    python meeting_guard.py run             # один проход
    python meeting_guard.py worker          # проход каждые MEETING_GUARD_INTERVAL секунд
    python meeting_guard.py log             # последние решения из журнала

Настройки — в .env (MEETING_GUARD_*). По умолчанию выключен: без
MEETING_GUARD_ENABLED=true проход ничего не делает. Первый проход только
запоминает момент включения — обрабатываются переходы после него.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.append(os.getcwd())

from app import create_app
from app.core.extensions import db
from app.models.automation_models import AutoMeetingLog
from app.services import macro_api_service, meeting_guard_service

INTERVAL_SECONDS = int(os.environ.get('MEETING_GUARD_INTERVAL', '600'))


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def main():
    parser = argparse.ArgumentParser(description='Страж встреч')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('types', help='справочник типов задач')
    check = sub.add_parser('check', help='разобрать одну заявку без записи')
    check.add_argument('lead_id', type=int)
    sub.add_parser('run', help='один проход')
    sub.add_parser('worker', help='проходы по расписанию')
    journal = sub.add_parser('log', help='журнал решений')
    journal.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db.create_all(bind_key='planning_db')

        if args.command == 'types':
            types = macro_api_service.call_raw('tasks/listTasksTypes', {})
            print(json.dumps(meeting_guard_service._unwrap(types), ensure_ascii=False, indent=1))
            return

        if args.command == 'check':
            report = meeting_guard_service.check_lead(args.lead_id)
            print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
            return

        if args.command == 'log':
            rows = AutoMeetingLog.query.order_by(AutoMeetingLog.id.desc()).limit(args.limit).all()
            for row in rows:
                print(f'{row.updated_at or row.created_at:%d.%m %H:%M}  заявка {row.estate_buy_id}  '
                      f'сделка {row.deal_id}  дом {row.house_id}  менеджер {row.manager_id}  '
                      f'→ {row.decision}'
                      + (f'  задача {row.task_id}' if row.task_id else '')
                      + (f'  найдена {row.found_task_id}' if row.found_task_id else '')
                      + (f'  ошибка: {row.error}' if row.error else ''))
            if not rows:
                print('Журнал пуст.')
            return

        if args.command == 'run':
            log(f'Проход: {meeting_guard_service.run_once()}')
            return

        log(f'Страж встреч запущен, проход каждые {INTERVAL_SECONDS} с.')
        while True:
            try:
                log(f'Проход: {meeting_guard_service.run_once()}')
            except Exception as e:
                db.session.rollback()
                log(f'Ошибка прохода: {e}')
            time.sleep(INTERVAL_SECONDS)


if __name__ == '__main__':
    main()

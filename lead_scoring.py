"""Скоринг входящих лидов — тестовый режим.

Команды:
    python lead_scoring.py train                 # обучить новую версию и сделать её активной
    python lead_scoring.py train --horizon 90    # другой горизонт метки «бронь», дней
    python lead_scoring.py score                 # оценить заявки последних 3 дней
    python lead_scoring.py score --days 30       # оценить за больший период (первый запуск)
    python lead_scoring.py worker                # оценивать новые заявки раз в час

Модель читает витрину Macro и пишет оценки в planning_db. В работу
колл-центра оценки не попадают — их видно только на странице
«Маркетинг → Скоринг лидов (тест)».
"""

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.append(os.getcwd())

from app import create_app
from app.core.extensions import db
from app.services import lead_scoring_service

WORKER_INTERVAL_SECONDS = int(os.environ.get('LEAD_SCORING_INTERVAL', '3600'))


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def main():
    parser = argparse.ArgumentParser(description='Скоринг входящих лидов (тест)')
    sub = parser.add_subparsers(dest='command', required=True)
    train = sub.add_parser('train', help='обучить модель')
    train.add_argument('--horizon', type=int, default=lead_scoring_service.DEFAULT_HORIZON_DAYS)
    train.add_argument('--no-activate', action='store_true', help='не делать новую версию активной')
    score = sub.add_parser('score', help='оценить новые заявки')
    score.add_argument('--days', type=int, default=3)
    sub.add_parser('worker', help='оценивать новые заявки по расписанию')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # Таблицы скоринга новые: без этого первый запуск упал бы на их отсутствии.
        db.create_all(bind_key='planning_db')

        if args.command == 'train':
            record = lead_scoring_service.train(horizon_days=args.horizon,
                                                activate=not args.no_activate)
            metrics = record.metrics
            log(f"Модель v{record.version}: ROC-AUC {metrics['roc_auc']}, "
                f"броней в топ-10/20/30%: {metrics['capture']['10']}/{metrics['capture']['20']}/"
                f"{metrics['capture']['30']}%")
            for grade in metrics['grades']:
                log(f"  группа {grade['grade']}: {grade['leads_share']}% заявок, "
                    f"конверсия {grade['booking_rate']}%, {grade['bookings_share']}% всех броней")
            return

        if args.command == 'score':
            log(f'Оценка заявок за {args.days} дн.: {lead_scoring_service.score_recent(days=args.days)}')
            return

        log(f'Воркер скоринга запущен, проверка каждые {WORKER_INTERVAL_SECONDS} с.')
        while True:
            try:
                log(f'Оценка: {lead_scoring_service.score_recent(days=3)}')
            except Exception as e:
                db.session.rollback()
                log(f'Ошибка оценки: {e}')
            time.sleep(WORKER_INTERVAL_SECONDS)


if __name__ == '__main__':
    main()

# app/services/debt_reminder_service.py
"""Ежедневные напоминания менеджерам о дебиторке.

Сообщения уходят через бота-нотификатора шлюза: получатель — логин
пользователя, привязку логина к чату Telegram держит шлюз. Своего бота,
подписки с кодом и chat_id здесь нет и не нужно.

Рассылку дёргает scheduler.py — здесь только логика, чтобы её можно было
проверить без сети.
"""

import logging
from datetime import date, datetime

import requests
from flask import current_app

from ..core.db_utils import get_planning_session
from app.models.planning_models import DebtReminderSubscription
from . import receivables_service
from .notification_client import NotificationServiceClient

logger = logging.getLogger(__name__)

# Сколько строк графика показываем в сообщении: остальное менеджер смотрит в отчёте.
REMINDER_ROWS_LIMIT = 5


# --- Подписка ---

def get_subscription(username):
    """Подписка пользователя или None."""
    if not username:
        return None
    return get_planning_session().query(DebtReminderSubscription).get(str(username))


def set_active(username, manager_id=None, active=True):
    """Включает или выключает напоминания для пользователя."""
    username = (username or '').strip()
    if not username:
        return None

    planning_session = get_planning_session()
    subscription = planning_session.query(DebtReminderSubscription).get(username)
    if not subscription:
        # Час рассылки общий и берётся из конфига: персональное время пока
        # никто не просил, а поле в модели оставляет такую возможность.
        subscription = DebtReminderSubscription(
            username=username,
            notify_hour=current_app.config.get('DEBT_REMINDER_HOUR', 9))
        planning_session.add(subscription)

    if manager_id is not None:
        subscription.manager_id = manager_id
    subscription.is_active = bool(active)
    planning_session.commit()
    return subscription


def subscription_status(username, manager_id=None):
    """Состояние подписки для вкладки уведомлений."""
    subscription = get_subscription(username)
    return {
        'subscription': subscription,
        'connected': bool(subscription and subscription.is_active),
        'notify_hour': (subscription.notify_hour if subscription
                        else current_app.config.get('DEBT_REMINDER_HOUR', 9)),
        'manager_linked': bool(manager_id),
    }


# --- Текст ---

def _money(value):
    """Сумма с пробелами вместо запятых — но только в самом числе."""
    return f'{value or 0:,.0f}'.replace(',', ' ')


def _plural(count, one, few, many):
    """Русское склонение: 1 платёж, 2 платежа, 5 платежей."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def _object_label(row):
    flat = f" №{row['flat_number']}" if row['flat_number'] else ''
    return f"{row['complex_name'] or '—'}{flat}"


def build_reminder_text(manager_id, today=None):
    """Текст напоминания. None — напоминать не о чем."""
    data = receivables_service.get_manager_receivables(manager_id, today=today)
    overdue, upcoming = data['overdue'], data['upcoming']
    if not overdue and not upcoming:
        return None

    lines = ['<b>Дебиторка по вашим сделкам</b>']

    if overdue:
        payments = _plural(len(overdue), 'платёж', 'платежа', 'платежей')
        lines.append(f"\n🔴 <b>Просрочено:</b> {_money(data['totals']['overdue'])} UZS "
                     f"({len(overdue)} {payments})")
        for row in overdue[:REMINDER_ROWS_LIMIT]:
            days = _plural(row['days_overdue'], 'день', 'дня', 'дней')
            lines.append(f"• {_object_label(row)} — {_money(row['amount'])} UZS, "
                         f"просрочка {row['days_overdue']} {days}")
        if len(overdue) > REMINDER_ROWS_LIMIT:
            lines.append(f'… и ещё {len(overdue) - REMINDER_ROWS_LIMIT}')

    if upcoming:
        payments = _plural(len(upcoming), 'платёж', 'платежа', 'платежей')
        lines.append(f"\n🟡 <b>Ближайшие платежи:</b> {_money(data['totals']['upcoming'])} UZS "
                     f"({len(upcoming)} {payments})")
        for row in upcoming[:REMINDER_ROWS_LIMIT]:
            due = row['due_date'].strftime('%d.%m') if row['due_date'] else '—'
            lines.append(f"• {due} — {_money(row['amount'])} UZS, {_object_label(row)}")
        if len(upcoming) > REMINDER_ROWS_LIMIT:
            lines.append(f'… и ещё {len(upcoming) - REMINDER_ROWS_LIMIT}')

    return '\n'.join(lines)


# --- Отправка ---

def send_reminder(username, text):
    """Отправляет напоминание через нотификатор шлюза."""
    try:
        NotificationServiceClient().send_telegram(username, text)
        return True
    except requests.RequestException as e:
        logger.error("Не удалось отправить напоминание %s: %s", username, e)
        return False


def due_subscriptions(now=None):
    """Кому пора отправлять напоминание прямо сейчас.

    Отбираем по часу отправки и по тому, что сегодня ещё не отправляли:
    планировщик просыпается чаще раза в день, и без этой отметки менеджер
    получал бы напоминание на каждом круге.
    """
    now = now or datetime.now()
    planning_session = get_planning_session()
    return [
        subscription
        for subscription in planning_session.query(DebtReminderSubscription).filter_by(is_active=True).all()
        if subscription.notify_hour == now.hour and subscription.last_sent_date != now.date()
    ]


def mark_sent(subscription, sent_date=None):
    """Помечает, что напоминание за сегодня ушло."""
    subscription.last_sent_date = sent_date or date.today()
    get_planning_session().commit()


def send_due_reminders(now=None):
    """Рассылает напоминания тем, у кого настал их час. Возвращает счётчики."""
    sent = skipped = 0
    for subscription in due_subscriptions(now):
        text = build_reminder_text(subscription.manager_id)
        if not text:
            # Долгов нет — молчим, но день отмечаем, чтобы не пересчитывать.
            mark_sent(subscription)
            skipped += 1
            continue

        if send_reminder(subscription.username, text):
            mark_sent(subscription)
            sent += 1
        else:
            skipped += 1

    return {'sent': sent, 'skipped': skipped}

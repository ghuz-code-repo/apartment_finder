# app/services/telegram_reminder_service.py
"""Подписка менеджеров на напоминания о дебиторке в Telegram.

Логин из шлюза и чат Telegram связать нечем, поэтому подписка идёт через
одноразовый код: менеджер жмёт кнопку в отчёте, открывает бота по ссылке с
кодом, и бот при /start подставляет к коду свой chat_id.

Отправку и разбор апдейтов дёргает отдельный воркер telegram_bot.py — здесь
только логика, чтобы её можно было проверить без сети.
"""

import secrets
from datetime import date, datetime

import requests
from flask import current_app

from ..core.db_utils import get_planning_session
from app.models.planning_models import TelegramSubscription
from . import receivables_service

TELEGRAM_API = 'https://api.telegram.org/bot{token}/{method}'
REQUEST_TIMEOUT = 20


# --- Подписка ---

def get_subscription(username):
    """Подписка пользователя или None."""
    if not username:
        return None
    return get_planning_session().query(TelegramSubscription).get(str(username))


def issue_link_code(username, manager_id=None):
    """Выдаёт (или перевыпускает) код привязки и возвращает подписку.

    Перевыпуск нужен, если менеджер потерял ссылку или сменил телефон: старый
    код при этом перестаёт работать.
    """
    username = (username or '').strip()
    if not username:
        return None

    planning_session = get_planning_session()
    subscription = planning_session.query(TelegramSubscription).get(username)
    if not subscription:
        # Час рассылки общий для всех и берётся из конфига: персональное время
        # пока никто не просил, а поле в модели оставляет такую возможность.
        subscription = TelegramSubscription(
            username=username,
            notify_hour=current_app.config.get('TELEGRAM_REMINDER_HOUR', 9))
        planning_session.add(subscription)

    subscription.manager_id = manager_id
    subscription.link_code = secrets.token_urlsafe(12)
    planning_session.commit()
    return subscription


def confirm_by_code(code, chat_id):
    """Привязывает чат к подписке по коду. Вызывается воркером на /start."""
    code = (code or '').strip()
    if not code or not chat_id:
        return None

    planning_session = get_planning_session()
    subscription = planning_session.query(TelegramSubscription).filter_by(link_code=code).first()
    if not subscription:
        return None

    subscription.chat_id = str(chat_id)
    subscription.is_active = True
    subscription.confirmed_at = datetime.now()
    planning_session.commit()
    return subscription


def deactivate(username=None, chat_id=None):
    """Отключает напоминания — из интерфейса по логину, из бота по чату."""
    planning_session = get_planning_session()
    query = planning_session.query(TelegramSubscription)
    if username:
        subscription = query.get(str(username))
    elif chat_id:
        subscription = query.filter_by(chat_id=str(chat_id)).first()
    else:
        return False

    if not subscription:
        return False

    subscription.is_active = False
    planning_session.commit()
    return True


def bot_link(subscription):
    """Ссылка-приглашение в бота. Без логина бота в конфиге ссылки нет."""
    bot_username = (current_app.config.get('TELEGRAM_BOT_USERNAME') or '').lstrip('@')
    if not bot_username or not subscription or not subscription.link_code:
        return None
    return f'https://t.me/{bot_username}?start={subscription.link_code}'


def subscription_status(username, manager_id=None):
    """Состояние подписки для вкладки уведомлений."""
    subscription = get_subscription(username)
    return {
        'subscription': subscription,
        'connected': bool(subscription and subscription.is_active and subscription.chat_id),
        'link': bot_link(subscription),
        'bot_configured': bool(current_app.config.get('TELEGRAM_BOT_USERNAME')
                               and current_app.config.get('TELEGRAM_BOT_TOKEN')),
        'manager_linked': bool(manager_id),
    }


# --- Отправка ---

def send_message(chat_id, text):
    """Отправляет сообщение. Ошибку логируем, но наверх не роняем."""
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    if not token or not chat_id:
        return False

    try:
        response = requests.post(
            TELEGRAM_API.format(token=token, method='sendMessage'),
            json={'chat_id': chat_id, 'text': text,
                  'parse_mode': 'HTML', 'disable_web_page_preview': True},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            current_app.logger.warning(f'Telegram sendMessage {response.status_code}: {response.text}')
            return False
        return True
    except requests.RequestException as e:
        current_app.logger.error(f'Telegram sendMessage failed: {e}')
        return False


# Сколько строк графика показываем в сообщении: остальное менеджер смотрит в отчёте.
REMINDER_ROWS_LIMIT = 5


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


def due_subscriptions(now=None):
    """Кому пора отправлять напоминание прямо сейчас.

    Отбираем по часу отправки и по тому, что сегодня ещё не отправляли:
    воркер просыпается чаще раза в день, и без этой отметки менеджер получал бы
    напоминание на каждом круге.
    """
    now = now or datetime.now()
    planning_session = get_planning_session()
    return [
        subscription
        for subscription in planning_session.query(TelegramSubscription).filter_by(is_active=True).all()
        if subscription.chat_id
        and subscription.notify_hour == now.hour
        and subscription.last_sent_date != now.date()
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

        if send_message(subscription.chat_id, text):
            mark_sent(subscription)
            sent += 1
        else:
            skipped += 1

    return {'sent': sent, 'skipped': skipped}


def handle_update(update):
    """Разбирает апдейт Telegram. Возвращает текст ответа или None."""
    message = (update or {}).get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')
    text = (message.get('text') or '').strip()
    if not chat_id or not text:
        return None

    if text.startswith('/start'):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ''
        if not code:
            return ('Чтобы подключить напоминания, откройте отчёт «Планы менеджеров» → '
                    'вкладка «Уведомления» и перейдите по персональной ссылке.')

        subscription = confirm_by_code(code, chat_id)
        if not subscription:
            return 'Ссылка устарела. Откройте вкладку «Уведомления» в отчёте и получите новую.'
        return ('Готово! Буду напоминать о просроченной и ближайшей дебиторке '
                'по вашим сделкам. Отключить — команда /stop.')

    if text.startswith('/stop'):
        if deactivate(chat_id=chat_id):
            return 'Напоминания отключены. Включить снова можно из отчёта.'
        return 'Активной подписки на этот чат нет.'

    return 'Команды: /start — подключить напоминания, /stop — отключить.'

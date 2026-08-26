# app/services/debt_reminder_service.py
"""Ежедневные напоминания менеджерам о дебиторке.

Сообщения уходят через notification-service, а в Telegram их отправляет
единственный бот портала — своего заводить нельзя, второй getUpdates с тем же
токеном ломает long polling.

Получателя портал резолвит по telegram-нику (поле telegram_username в
auth-service), а не по логину, поэтому ник храним у себя. Сам чат менеджер
привязывает в личном кабинете портала; пока он этого не сделал, уведомление
уходит в failed.

Текст разбирается как Markdown, причём легаси-версия ломается на
несбалансированных '*', '_', '[' и обратных кавычках, поэтому любые
подставляемые данные экранируются.

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

# Как часто напоминать. Ключ пишется в подписку, подпись идёт во вкладку.
INTERVALS = (
    ('day', 'Раз в день'),
    ('hour', 'Раз в час'),
)
DEFAULT_INTERVAL = 'day'


# --- Подписка ---

def get_subscription(username):
    """Подписка пользователя или None."""
    if not username:
        return None
    return get_planning_session().query(DebtReminderSubscription).get(str(username))


def normalize_recipient(value):
    """Приводит получателя к тому виду, который ждёт notification-service.

    Число — готовый chat_id, всё остальное — telegram-ник, и '@' в нём лишний:
    портал ищет ник без собачки.
    """
    value = (value or '').strip()
    if not value:
        return None
    if value.lstrip('-').isdigit():
        return value
    return value.lstrip('@')


def normalize_interval(value):
    """Интервал из формы. Незнакомое значение -> ежедневно."""
    return value if value in dict(INTERVALS) else DEFAULT_INTERVAL


def normalize_hour(value, fallback=None):
    """Час отправки 0-23. Мусор -> текущее значение или общий из конфига."""
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return fallback if fallback is not None else current_app.config.get('DEBT_REMINDER_HOUR', 9)
    return hour if 0 <= hour <= 23 else 0


def set_active(username, manager_id=None, active=True, recipient=None,
               interval=None, notify_hour=None):
    """Создаёт или обновляет подписку пользователя."""
    username = (username or '').strip()
    if not username:
        return None

    planning_session = get_planning_session()
    subscription = planning_session.query(DebtReminderSubscription).get(username)
    if not subscription:
        subscription = DebtReminderSubscription(
            username=username,
            interval=DEFAULT_INTERVAL,
            notify_hour=current_app.config.get('DEBT_REMINDER_HOUR', 9))
        planning_session.add(subscription)

    if manager_id is not None:
        subscription.manager_id = manager_id
    if recipient is not None:
        subscription.telegram_recipient = normalize_recipient(recipient)
    if interval is not None:
        subscription.interval = normalize_interval(interval)
    if notify_hour is not None:
        subscription.notify_hour = normalize_hour(notify_hour, subscription.notify_hour)
    subscription.is_active = bool(active)
    planning_session.commit()
    return subscription


def subscription_status(username, manager_id=None):
    """Состояние подписки для вкладки уведомлений."""
    subscription = get_subscription(username)
    return {
        'subscription': subscription,
        'connected': bool(subscription and subscription.is_active
                          and subscription.telegram_recipient),
        'recipient': subscription.telegram_recipient if subscription else None,
        'interval': subscription.interval if subscription else DEFAULT_INTERVAL,
        'intervals': INTERVALS,
        'notify_hour': (subscription.notify_hour if subscription
                        else current_app.config.get('DEBT_REMINDER_HOUR', 9)),
        'last_sent_at': subscription.last_sent_at if subscription else None,
        'manager_linked': bool(manager_id),
    }


# --- Текст ---

def escape_markdown(text):
    """Экранирует спецсимволы легаси-Markdown в подставляемых данных.

    Название ЖК с '_' или '[' в тексте без экранирования роняет разбор, и
    сообщение молча уходит в failed с 'can\'t parse entities'.
    """
    text = '' if text is None else str(text)
    for char in ('\\', '`', '*', '_', '[', ']'):
        text = text.replace(char, '\\' + char)
    return text


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
    return escape_markdown(f"{row['complex_name'] or '—'}{flat}")


def report_link():
    """Абсолютная ссылка на отчёт: внутренние адреса из Telegram недоступны."""
    base = current_app.config.get('PUBLIC_BASE_URL')
    if not base:
        return None
    return f'{base}/reports/manager-performance-report'


# Заголовок бот выводит жирной первой строкой, поэтому в текст его не дублируем.
REMINDER_SUBJECT = 'Дебиторка по вашим сделкам'


def build_reminder_text(manager_id, today=None):
    """Текст напоминания в Markdown. None — напоминать не о чем."""
    data = receivables_service.get_manager_receivables(manager_id, today=today)
    overdue, upcoming = data['overdue'], data['upcoming']
    if not overdue and not upcoming:
        return None

    lines = []

    if overdue:
        payments = _plural(len(overdue), 'платёж', 'платежа', 'платежей')
        lines.append(f"🔴 *Просрочено:* {_money(data['totals']['overdue'])} UZS "
                     f"({len(overdue)} {payments})")
        for row in overdue[:REMINDER_ROWS_LIMIT]:
            days = _plural(row['days_overdue'], 'день', 'дня', 'дней')
            lines.append(f"• {_object_label(row)} — {_money(row['amount'])} UZS, "
                         f"просрочка {row['days_overdue']} {days}")
        if len(overdue) > REMINDER_ROWS_LIMIT:
            lines.append(f'… и ещё {len(overdue) - REMINDER_ROWS_LIMIT}')

    if upcoming:
        payments = _plural(len(upcoming), 'платёж', 'платежа', 'платежей')
        if lines:
            lines.append('')
        lines.append(f"🟡 *Ближайшие платежи:* {_money(data['totals']['upcoming'])} UZS "
                     f"({len(upcoming)} {payments})")
        for row in upcoming[:REMINDER_ROWS_LIMIT]:
            due = row['due_date'].strftime('%d.%m') if row['due_date'] else '—'
            lines.append(f"• {due} — {_money(row['amount'])} UZS, {_object_label(row)}")
        if len(upcoming) > REMINDER_ROWS_LIMIT:
            lines.append(f'… и ещё {len(upcoming) - REMINDER_ROWS_LIMIT}')

    link = report_link()
    if link:
        lines.append('')
        lines.append(f'[Открыть отчёт]({link})')

    return '\n'.join(lines)


# --- Отправка ---

# Текст проверочного сообщения: кнопка «Проверить» должна доказать доставку
# даже тогда, когда напоминать не о чем.
TEST_SUBJECT = 'Проверка уведомлений'
TEST_TEXT = ('Проверка связи: уведомления о дебиторке настроены и доходят.\n'
             'Если вы видите это сообщение — всё работает.')


def send_message(recipient, text, subject=REMINDER_SUBJECT):
    """Отправляет сообщение и возвращает (успех, что ответил сервис).

    Доставка асинхронная: сервис кладёт уведомление в очередь и отвечает id и
    статусом pending. «Telegram не привязан» всплывёт уже там, статусом failed,
    поэтому успех здесь означает только то, что очередь приняла сообщение.
    """
    logger.info("Отправляю уведомление о дебиторке: recipient=%s", recipient)
    try:
        response = NotificationServiceClient().send_telegram(recipient, text, subject=subject)
    except requests.RequestException as e:
        logger.error("Не удалось отправить уведомление %s: %s", recipient, e)
        return False, str(e)
    except Exception as e:
        # Сервис мог ответить не-JSON или упасть иначе: для кнопки проверки
        # важно показать причину, а не молча вернуть «не отправлено».
        logger.exception("Ошибка отправки уведомления %s", recipient)
        return False, str(e)

    logger.info("Уведомление принято сервисом: recipient=%s, ответ=%s", recipient, response)
    return True, response


def send_reminder(recipient, text):
    """Совместимая обёртка: только признак успеха."""
    ok, _detail = send_message(recipient, text)
    return ok


def is_due(subscription, now=None):
    """Пора ли отправлять этой подписке.

    Дневной режим: не раньше назначенного часа и не повторно за сутки. Час
    сравнивается как «не раньше», иначе редкий обход мог перешагнуть его целиком.
    Часовой режим: прошёл час с прошлой отправки.
    """
    now = now or datetime.now()

    # Без получателя слать некуда: уведомление ушло бы в failed.
    if not subscription.is_active or not subscription.telegram_recipient:
        return False

    if subscription.interval == 'hour':
        last = subscription.last_sent_at
        return last is None or (now - last).total_seconds() >= 3600

    return (now.hour >= (subscription.notify_hour or 0)
            and subscription.last_sent_date != now.date())


def due_subscriptions(now=None):
    """Кому пора отправлять напоминание прямо сейчас."""
    now = now or datetime.now()
    planning_session = get_planning_session()
    return [
        subscription
        for subscription in planning_session.query(DebtReminderSubscription).filter_by(is_active=True).all()
        if is_due(subscription, now)
    ]


def mark_sent(subscription, now=None):
    """Помечает, что уведомление отправлено."""
    now = now or datetime.now()
    subscription.last_sent_at = now
    subscription.last_sent_date = now.date()
    get_planning_session().commit()


def send_due_reminders(now=None):
    """Рассылает напоминания тем, кому пора. Возвращает счётчики."""
    now = now or datetime.now()
    sent = skipped = quiet = 0

    for subscription in due_subscriptions(now):
        text = build_reminder_text(subscription.manager_id)
        if not text:
            # Долгов нет — молчим, но отметку ставим, чтобы не пересчитывать
            # одно и то же на каждом круге.
            mark_sent(subscription, now)
            quiet += 1
            continue

        ok, _detail = send_message(subscription.telegram_recipient, text)
        if ok:
            mark_sent(subscription, now)
            sent += 1
        else:
            skipped += 1

    logger.info("Рассылка дебиторки: отправлено=%s, без долгов=%s, ошибок=%s",
                sent, quiet, skipped)
    return {'sent': sent, 'quiet': quiet, 'skipped': skipped}


def send_test(username, today=None):
    """Немедленная отправка по кнопке «Проверить». Возвращает (успех, текст)."""
    subscription = get_subscription(username)
    if not subscription or not subscription.telegram_recipient:
        return False, 'Сначала укажите telegram-ник или chat_id и сохраните настройки.'

    # Если долгов нет, всё равно шлём: кнопка проверяет доставку, а не наличие
    # дебиторки.
    text = build_reminder_text(subscription.manager_id, today=today)
    subject = REMINDER_SUBJECT if text else TEST_SUBJECT
    ok, detail = send_message(subscription.telegram_recipient, text or TEST_TEXT, subject=subject)

    if not ok:
        return False, f'Сервис уведомлений вернул ошибку: {detail}'

    notification_id = detail.get('id') if isinstance(detail, dict) else None
    message = f'Сообщение отправлено получателю {subscription.telegram_recipient}.'
    if notification_id:
        message += f' Номер уведомления: {notification_id}.'
    message += (' Доставка асинхронная: если сообщение не пришло, проверьте, что'
                ' Telegram привязан в личном кабинете портала и ник указан верно.')
    return True, message

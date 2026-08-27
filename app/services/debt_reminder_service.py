# app/services/debt_reminder_service.py
"""Ежедневные напоминания менеджерам о дебиторке.

Сообщения уходят через notification-service, а в Telegram их отправляет
единственный бот портала — своего заводить нельзя, второй getUpdates с тем же
токеном ломает long polling.

Получателя адресуем логином портала: chat_id по нему находит сам
notification-service через auth-service. Ник и chat_id у себя не храним — это
был бы второй источник правды, который рано или поздно разойдётся с первым.

Резолв идёт на приёме запроса, поэтому отказ приходит сразу и с машинным
кодом: «Telegram не привязан» и «нет доступа к сервису» — разные проблемы с
разным лечением, и пользователю показывается именно его случай.

Текст разбирается как Markdown, причём легаси-версия ломается на
несбалансированных '*', '_', '[' и обратных кавычках, поэтому любые
подставляемые данные экранируются.

Рассылку дёргает reminder_worker.py — здесь только логика, чтобы её можно было
проверить без сети.
"""

import logging
from datetime import date, datetime

import requests
from flask import current_app

from ..core.db_utils import get_planning_session
from app.models.planning_models import DebtReminderSubscription
from . import gateway_client, manager_link_service, receivables_service
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


# Машинные коды отказа notification-service -> что делать пользователю.
FAILURE_HINTS = {
    'channel_not_linked': 'Telegram не подключён к порталу. Откройте личный кабинет '
                          '(Безопасность → Подключить Telegram) и повторите проверку.',
    'user_not_found': 'Ваш логин не найден на портале — обратитесь к администратору.',
    'user_banned': 'Учётная запись заблокирована на портале.',
    'no_address': 'В профиле портала не заполнен адрес для этого канала.',
    'no_service_access': 'У вашей учётной записи нет ролей в этом сервисе — '
                         'обратитесь к администратору портала.',
    'auth_unavailable': 'Сервис авторизации сейчас недоступен, уведомление не создано. '
                        'Попробуйте позже.',
}


def describe_failure(response):
    """Причина отказа человеческим языком плюс сам код."""
    payload = {}
    if response is not None:
        try:
            payload = response.json() or {}
        except ValueError:
            payload = {}

    code = payload.get('failure_code')
    hint = FAILURE_HINTS.get(code)
    if hint:
        return hint, code

    detail = payload.get('error') or payload.get('message') or (
        response.text[:200] if response is not None else '')
    return (detail or 'Сервис уведомлений отклонил запрос.'), code


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


def set_active(username, manager_id=None, active=True, interval=None, notify_hour=None):
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
    if interval is not None:
        subscription.interval = normalize_interval(interval)
    if notify_hour is not None:
        subscription.notify_hour = normalize_hour(notify_hour, subscription.notify_hour)
    subscription.is_active = bool(active)
    planning_session.commit()
    return subscription


def subscription_status(username, manager_id=None):
    """Состояние подписки для вкладки уведомлений.

    Заранее узнать, привязан ли Telegram, сервис не может — резолв живёт в
    шлюзе. Поэтому показываем итог последней попытки: он и отвечает на вопрос
    «доходит ли».
    """
    subscription = get_subscription(username)

    return {
        'subscription': subscription,
        'active': bool(subscription and subscription.is_active),
        'connected': bool(subscription and subscription.is_active
                          and subscription.last_status == 'ok'),
        'last_status': subscription.last_status if subscription else None,
        'last_error': subscription.last_error if subscription else None,
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


def send_message(login, text, subject=REMINDER_SUBJECT):
    """Отправляет сообщение по логину. Возвращает (успех, детали).

    Резолв адреса notification-service делает на приёме, поэтому отказ вида
    «Telegram не привязан» приходит здесь же, синхронно, а не теряется в
    очереди. Успех означает, что уведомление создано и поставлено в очередь.
    """
    logger.info("Отправляю уведомление о дебиторке: login=%s", login)
    try:
        response = NotificationServiceClient().send_telegram(login, text, subject=subject)
    except requests.HTTPError as e:
        # 400 и 503 несут машинный код отказа — по нему и объясняем.
        reason, code = describe_failure(e.response)
        logger.error("Уведомление для %s отклонено (%s): %s", login, code, reason)
        return False, {'reason': reason, 'failure_code': code}
    except requests.RequestException as e:
        logger.error("Сервис уведомлений недоступен (%s): %s", login, e)
        return False, {'reason': f'Сервис уведомлений недоступен: {e}', 'failure_code': None}
    except Exception as e:
        logger.exception("Ошибка отправки уведомления %s", login)
        return False, {'reason': str(e), 'failure_code': None}

    logger.info("Уведомление принято сервисом: login=%s, ответ=%s", login, response)
    return True, response


def _commit(what):
    """Коммит, который не роняет круг рассылки.

    База — SQLite на общем томе, в неё пишут и веб, и воркер, поэтому запись
    может упереться в «database is locked». Раньше такое исключение обрывало
    круг целиком: сообщение уже ушло, а отметка об отправке не сохранилась — и
    через пять минут всё повторялось заново. Отсюда и брались сотни одинаковых
    напоминаний.
    """
    try:
        get_planning_session().commit()
        return True
    except Exception as e:
        get_planning_session().rollback()
        logger.error("Не удалось сохранить %s: %s", what, e)
        return False


def remember_result(subscription, ok, detail):
    """Запоминает итог последней отправки — вкладка показывает именно его."""
    if not subscription:
        return
    subscription.last_status = 'ok' if ok else (
        (detail or {}).get('failure_code') or 'error')
    subscription.last_error = None if ok else (detail or {}).get('reason')
    _commit('итог отправки')


def is_due(subscription, now=None):
    """Пора ли отправлять этой подписке.

    Дневной режим: не раньше назначенного часа и не повторно за сутки. Час
    сравнивается как «не раньше», иначе редкий обход мог перешагнуть его целиком.
    Часовой режим: прошёл час с прошлой отправки.
    """
    now = now or datetime.now()

    if not subscription.is_active:
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
    """Помечает, что уведомление отправлено.

    Ставится ДО отправки: неудачная отправка стоит одного пропущенного
    напоминания, а несохранённая отметка — бесконечного потока одинаковых
    сообщений. Из двух отказов первый безопаснее.
    """
    now = now or datetime.now()
    subscription.last_sent_at = now
    subscription.last_sent_date = now.date()
    return _commit('отметку об отправке')


def refresh_manager_link(subscription, users):
    """Сверяет менеджера подписки с текущей связкой логина.

    manager_id пишется в подписку в момент настройки — это снимок. Связку
    «логин ↔ менеджер CRM» админ потом меняет: переносит на другого человека,
    удаляет, или совпадение по ФИО перестаёт работать. Снимок при этом остаётся
    прежним, и напоминания продолжают уходить старому логину — с чужой
    дебиторкой. Поэтому перед каждой отправкой связка пересчитывается.

    Returns:
        (manager_id, готова_ли_подписка_к_отправке)
    """
    manager_id, resolved = manager_link_service.manager_id_for(subscription.username, users)

    if not resolved:
        # Шлюз не ответил: гасить подписку по этой причине нельзя
        logger.warning("Связка логина %s не проверена — пропускаю круг", subscription.username)
        return None, False

    if manager_id == subscription.manager_id:
        return manager_id, True

    if manager_id is None:
        # Связки больше нет: слать чужую дебиторку этому логину нельзя
        logger.warning("Логин %s больше не связан с менеджером %s — подписка отключена",
                       subscription.username, subscription.manager_id)
        subscription.is_active = False
        subscription.manager_id = None
        subscription.last_status = 'manager_unlinked'
        subscription.last_error = ('Логин больше не связан с менеджером CRM. '
                                   'Свяжитесь с администратором и включите напоминания заново.')
        _commit('отключение подписки')
        return None, False

    logger.info("Логин %s теперь связан с менеджером %s (был %s) — подписка обновлена",
                subscription.username, manager_id, subscription.manager_id)
    subscription.manager_id = manager_id
    _commit('обновление связки подписки')
    return manager_id, True


def send_due_reminders(now=None):
    """Рассылает напоминания тем, кому пора. Возвращает счётчики."""
    now = now or datetime.now()
    sent = skipped = quiet = 0

    # Список пользователей шлюза берём один раз на круг: он нужен для проверки
    # связок, а подписок может быть много. None — шлюз недоступен.
    users = gateway_client.list_service_users()

    for subscription in due_subscriptions(now):
        manager_id, ready = refresh_manager_link(subscription, users)
        if not ready:
            skipped += 1
            continue

        text = build_reminder_text(manager_id) if manager_id else None
        if not text:
            # Долгов нет — молчим, но отметку ставим, чтобы не пересчитывать
            # одно и то же на каждом круге.
            mark_sent(subscription, now)
            quiet += 1
            continue

        # Отметка идёт первой: если её не удалось сохранить, отправлять нельзя —
        # иначе следующий круг сочтёт, что отправки не было, и пошлёт снова.
        if not mark_sent(subscription, now):
            logger.error("Пропускаю %s: отметку об отправке сохранить не удалось",
                         subscription.username)
            skipped += 1
            continue

        ok, detail = send_message(subscription.username, text)
        remember_result(subscription, ok, detail)
        if ok:
            sent += 1
        else:
            skipped += 1

    logger.info("Рассылка дебиторки: отправлено=%s, без долгов=%s, ошибок=%s",
                sent, quiet, skipped)
    return {'sent': sent, 'quiet': quiet, 'skipped': skipped}


def send_test(username, today=None):
    """Немедленная отправка по кнопке «Проверить». Возвращает (успех, текст)."""
    if not username:
        return False, 'Не удалось определить пользователя.'

    subscription = get_subscription(username)

    # Кнопку жмёт сам пользователь, поэтому связку берём актуальную, а не снимок
    # из подписки: иначе проверка покажет чужую дебиторку.
    manager_id = manager_link_service.current_manager_id()
    if manager_id is None and subscription:
        manager_id = subscription.manager_id

    # Если долгов нет, всё равно шлём: кнопка проверяет доставку, а не наличие
    # дебиторки.
    text = build_reminder_text(manager_id, today=today) if manager_id else None
    subject = REMINDER_SUBJECT if text else TEST_SUBJECT
    ok, detail = send_message(username, text or TEST_TEXT, subject=subject)
    remember_result(subscription, ok, detail)

    if not ok:
        return False, detail.get('reason', 'Отправить не удалось.')

    notification_id = detail.get('id') if isinstance(detail, dict) else None
    message = 'Уведомление принято сервисом и поставлено в очередь.'
    if notification_id:
        message += f' Номер: {notification_id}.'
    message += (' Если сообщение так и не пришло, посмотрите статус этого номера'
                ' в сервисе уведомлений.')
    return True, message

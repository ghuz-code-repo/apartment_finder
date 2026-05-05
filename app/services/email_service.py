# app/services/email_service.py
"""
Тонкая обёртка над notification-service для рассылки HTML-писем.
Локальный SMTP больше не используется — вся отправка централизована.
"""

from typing import List

import requests
from flask import current_app

from .notification_client import NotificationServiceClient


def _resolve_recipients() -> List[str]:
    """Достаёт список получателей из конфига Flask (поддерживает list и CSV-строку)."""
    raw = current_app.config.get('MAIL_RECIPIENTS', '')
    if isinstance(raw, (list, tuple)):
        return [str(r).strip() for r in raw if str(r).strip()]
    return [r.strip() for r in str(raw).split(',') if r.strip()]


def send_email(subject, html_body):
    """Отправляет HTML-письмо всем получателям через notification-service."""
    recipients = _resolve_recipients()

    print("\n" + "=" * 50)
    print("[EMAIL SERVICE] 📨 Отправка через notification-service")
    print(f"[EMAIL SERVICE] Получатели: {recipients}")
    print(f"[EMAIL SERVICE] Тема: {subject}")

    if not recipients:
        print("[EMAIL SERVICE] ❕ Список получателей пуст. Отправка отменена.")
        print("=" * 50 + "\n")
        return

    client = NotificationServiceClient()

    try:
        if len(recipients) == 1:
            result = client.send_email(
                recipient=recipients[0],
                subject=subject,
                content=html_body,
                content_type='text/html',
            )
            print(f"[EMAIL SERVICE] ✅ Отправлено. ID: {result.get('id')}")
        else:
            result = client.send_email_batch(
                recipients=recipients,
                subject=subject,
                content=html_body,
                content_type='text/html',
            )
            print(f"[EMAIL SERVICE] ✅ Batch отправлен. batch_id: {result.get('batch_id')}")
    except requests.RequestException as e:
        # Не пробрасываем — провал почты не должен ломать основной flow
        # (например, активацию версии скидок).
        print(f"[EMAIL SERVICE] ❌ Ошибка вызова notification-service: {type(e).__name__}: {e}")
    finally:
        print("=" * 50 + "\n")
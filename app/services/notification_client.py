# app/services/notification_client.py
"""
Клиент для централизованного notification-service.
Все email из apartment_finder идут через него — локального SMTP больше нет.
"""

import os
import logging
from typing import Optional, Iterable, List

import requests

logger = logging.getLogger(__name__)


class NotificationServiceClient:
    """HTTP-клиент notification-service."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        self.base_url = (base_url or os.getenv(
            'NOTIFICATION_SERVICE_URL',
            'http://notification-service:80'
        )).rstrip('/')
        self.timeout = timeout if timeout is not None else int(
            os.getenv('NOTIFICATION_SERVICE_TIMEOUT', '10')
        )
        # Персональный ключ сервиса для аутентификации в notification-service
        self.api_key = os.getenv('NOTIFICATION_API_KEY') or os.getenv('INTERNAL_API_KEY', '')

    def _headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers['X-API-Key'] = self.api_key
        return headers

    def send_email(
        self,
        recipient: str,
        subject: str,
        content: str,
        content_type: str = 'text/plain',
    ) -> dict:
        """Отправляет одно email-уведомление."""
        payload = {
            'type': 'email',
            'recipient': recipient,
            'subject': subject,
            'content': content,
            'content_type': content_type,
        }

        logger.info(
            "Отправка email через notification-service: recipient=%s, subject=%s, content_type=%s",
            recipient, subject, content_type,
        )

        response = requests.post(
            f"{self.base_url}/api/v1/notifications",
            json=payload,
            timeout=self.timeout,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def send_telegram(self, recipient: str, content: str, subject: Optional[str] = None) -> dict:
        """Отправляет сообщение в Telegram через бота портала.

        recipient — либо готовый chat_id (число), либо telegram-ник: ник
        notification-service резолвит через auth-service, и это именно ник, а
        не логин на портале. content_type не передаём: бот жёстко разбирает
        текст как Markdown.
        """
        payload = {
            'type': 'telegram',
            'recipient': recipient,
            'content': content,
        }
        if subject:
            # Заголовок бот выводит жирной первой строкой.
            payload['subject'] = subject

        logger.info("Отправка telegram через notification-service: recipient=%s", recipient)

        response = requests.post(
            f"{self.base_url}/api/v1/notifications",
            json=payload,
            timeout=self.timeout,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    def send_email_batch(
        self,
        recipients: Iterable[str],
        subject: str,
        content: str,
        content_type: str = 'text/plain',
    ) -> dict:
        """Отправляет одно письмо нескольким получателям через batch-эндпоинт."""
        notifications: List[dict] = [
            {
                'type': 'email',
                'recipient': r,
                'subject': subject,
                'content': content,
                'content_type': content_type,
            }
            for r in recipients
        ]

        if not notifications:
            logger.warning("send_email_batch: пустой список получателей, отправка отменена")
            return {'batch_id': None, 'message': 'no recipients'}

        logger.info(
            "Отправка batch-email: count=%d, subject=%s, content_type=%s",
            len(notifications), subject, content_type,
        )

        response = requests.post(
            f"{self.base_url}/api/v1/notifications/batch",
            json={'notifications': notifications},
            timeout=self.timeout,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

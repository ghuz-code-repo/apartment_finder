import os
import requests
import json
import shutil
from werkzeug.utils import secure_filename
from flask import current_app, request
from app.core.extensions import db
from app.models.news_models import News, NewsMedia


def save_news(title, description, files):
    news_item = News(title=title, description=description)
    db.session.add(news_item)
    db.session.flush()

    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)

            # БЕЗОПАСНОЕ ПОЛУЧЕНИЕ РАСШИРЕНИЯ
            parts = filename.rsplit('.', 1)
            ext = parts[1].lower() if len(parts) > 1 else ""

            relative_path = f'uploads/news/{news_item.id}/{filename}'
            upload_path = os.path.join(current_app.static_folder, 'uploads', 'news', str(news_item.id))
            os.makedirs(upload_path, exist_ok=True)

            file.save(os.path.join(upload_path, filename))

            # Определение типа медиа
            media_type = 'video' if ext in ['mp4', 'mov', 'avi'] else 'image'

            media = NewsMedia(news_id=news_item.id, file_path=relative_path, media_type=media_type)
            db.session.add(media)

    db.session.commit()
    send_to_telegram(news_item)
    return news_item


def send_to_telegram(news_item):
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    chat_id = current_app.config.get('TELEGRAM_CHANNEL_ID')

    if not token or not chat_id:
        return

    caption = f"<b>{news_item.title}</b>\n\n{news_item.description}"

    if not news_item.media:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": caption,
            "parse_mode": "HTML"
        }, verify=False)
        return

    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    media_group = []
    files_to_send = {}

    for i, m in enumerate(news_item.media):
        file_full_path = os.path.join(current_app.static_folder, m.file_path)

        if os.path.exists(file_full_path):
            file_key = f"file_{i}"
            files_to_send[file_key] = open(file_full_path, 'rb')

            item = {
                "type": "photo" if m.media_type == "image" else "video",
                "media": f"attach://{file_key}"
            }
            if i == 0:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media_group.append(item)

    try:
        payload = {
            "chat_id": chat_id,
            "media": json.dumps(media_group)
        }
        response = requests.post(url, data=payload, files=files_to_send, timeout=30, verify=False)
        if not response.ok:
            print(f"Telegram API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Connection Error: {e}")
    finally:
        for f in files_to_send.values():
            f.close()


def delete_news(news_id):
    news = News.query.get(news_id)
    if news:
        upload_path = os.path.join(current_app.static_folder, 'uploads', 'news', str(news_id))
        if os.path.exists(upload_path):
            shutil.rmtree(upload_path)
        db.session.delete(news)
        db.session.commit()
        return True
    return False
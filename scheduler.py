# scheduler.py

import os
import time
from datetime import datetime
from app import create_app
from app.core.config import DevelopmentConfig
# <<< ИЗМЕНЕНО: Импортируем функцию инкрементного обновления >>>
from app.services.initial_load_service import incremental_update_from_mysql

# Создаем экземпляр приложения Flask, чтобы получить доступ к его контексту
app = create_app(DevelopmentConfig)

# Интервал в секундах (75 минут * 60 секунд)
SLEEP_INTERVAL = 75 * 60

# <<< НОВЫЙ КОД: Определяем путь к файлу блокировки >>>
# Путь должен быть таким же, как в __init__.py
LOCK_FILE_PATH = os.path.join(app.instance_path, 'update.lock')


def run_scheduler():
    """
    Бесконечный цикл, который запускает инкрементное обновление данных
    и управляет файлом блокировки.
    """
    print("--- [ПЛАНИРОВЩИК ЗАПУЩЕН] ---")
    while True:
        # Проверяем, не запущен ли уже другой процесс обновления
        if os.path.exists(LOCK_FILE_PATH):
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⚠️ Обновление уже запущено. Пропускаю...")
            time.sleep(SLEEP_INTERVAL)
            continue

        try:
            # --- ШАГ 1: Создаем файл блокировки ---
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]  блокирую базу данных для обновления...")
            with open(LOCK_FILE_PATH, 'w') as f:
                f.write('locked by scheduler')

            # --- ШАГ 2: Запускаем инкрементное обновление ---
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Начинаю инкрементное обновление данных...")
            with app.app_context():
                # <<< ИЗМЕНЕНО: Вызываем инкрементное обновление, а не полное >>>
                success = incremental_update_from_mysql()

            if success:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✔️ Обновление успешно завершено.")
            else:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Обновление завершилось с ошибкой.")

        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ КРИТИЧЕСКАЯ ОШИБКА в планировщике: {e}")

        finally:
            # --- ШАГ 3: Гарантированно удаляем файл блокировки ---
            if os.path.exists(LOCK_FILE_PATH):
                os.remove(LOCK_FILE_PATH)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ База данных разблокирована.")

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Следующее обновление через 75 минут...")
        time.sleep(SLEEP_INTERVAL)


if __name__ == '__main__':
    run_scheduler()
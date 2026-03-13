import os
import sqlalchemy
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('SOURCE_MYSQL_URI', '')
if not DB_URI:
    print("ERROR: SOURCE_MYSQL_URI not set in .env")
    exit(1)

print(f"--- [DEBUG] Пытаемся подключиться к MySQL ---")

try:
    engine = create_engine(DB_URI)

    with engine.connect() as connection:
        print("\n--- [DEBUG] УСПЕШНО ПОДКЛЮЧИЛИСЬ! ---")

        # 1. Проверяем столбцы в estate_sells
        print("\n--- 1. Столбцы в таблице 'estate_sells': ---")
        # text() нужен, чтобы SQLAlchemy выполнил запрос как "сырой" SQL
        columns_query = text("SHOW COLUMNS FROM estate_sells;")
        result_columns = connection.execute(columns_query)

        # Печатаем столбцы. Нас интересует `estate_sell_status_name`
        for row in result_columns:
            print(f"  - Имя: {row[0]}, Тип: {row[1]}")  # row[0] - это 'Field', row[1] - это 'Type'

        # 2. Проверяем РЕАЛЬНЫЕ статусы (это наша главная гипотеза)
        print("\n--- 2. Уникальные значения в 'estate_sell_status_name' и их количество: ---")
        status_query = text(
            "SELECT DISTINCT estate_sell_status_name, COUNT(*) as count FROM estate_sells GROUP BY estate_sell_status_name;")
        result_statuses = connection.execute(status_query)

        statuses_found = 0
        for row in result_statuses:
            print(f"  - Статус: '{row[0]}', Количество: {row[1]}")
            statuses_found += 1

        if statuses_found == 0:
            print("  - Не найдено ни одного статуса. Возможно, таблица 'estate_sells' пуста?")

except sqlalchemy.exc.OperationalError as e:
    print("\n--- [DEBUG] ❌ ОШИБКА ПОДКЛЮЧЕНИЯ ---")
    print(f"  - Не удалось подключиться. Проверьте IP (172.16.0.199), порт (9906) и доступ (VPN).")
    print(f"  - Ошибка: {e}")
except Exception as e:
    print(f"\n--- [DEBUG] ❌ НЕИЗВЕСТНАЯ ОШИБКА ---")
    print(f"  - Ошибка: {e}")
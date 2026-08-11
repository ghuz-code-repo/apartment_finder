"""Разведка: есть ли планировочные решения в реплике MacroCRM.

Мы читаем чужую базу и знаем в ней только четыре таблицы (estate_sells,
estate_houses, estate_deals, users). Прежде чем проектировать выдачу планировок,
надо выяснить, лежат ли они там вообще и в каком виде: путь к файлу, URL,
идентификатор во внешнем хранилище или ничего.

Скрипт ничего не меняет — только читает схему и по три примера значений.

Запуск (нужен доступ к MySQL MacroCRM):  python discover_macro_plans.py
"""
import os
import re

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DB_URI = os.environ.get('SOURCE_MYSQL_URI', '')

# Слова, по которым узнаём колонку с картинкой/планировкой.
COLUMN_HINTS = re.compile(
    r'plan|layout|scheme|schema|draw|image|img|photo|picture|file|media|'
    r'attach|url|link|path|src|preview|thumb',
    re.IGNORECASE,
)
TABLE_HINTS = re.compile(
    r'plan|layout|flat|estate|sell|file|image|media|attach|type|class',
    re.IGNORECASE,
)

SAMPLE_LIMIT = 3


def _fetch(connection, sql, **params):
    return connection.execute(text(sql), params).fetchall()


def main():
    if not DB_URI:
        print('ERROR: SOURCE_MYSQL_URI не задан в .env')
        return

    engine = create_engine(DB_URI)
    with engine.connect() as connection:
        database = _fetch(connection, 'SELECT DATABASE()')[0][0]
        print(f'База: {database}\n')

        tables = [row[0] for row in _fetch(connection, 'SHOW TABLES')]
        print(f'Всего таблиц: {len(tables)}')

        # 1. Таблицы, чьё имя намекает на планировки или файлы.
        interesting_tables = [t for t in tables if TABLE_HINTS.search(t)]
        print(f'\n--- 1. Таблицы-кандидаты ({len(interesting_tables)}) ---')
        for name in interesting_tables:
            count = _fetch(connection, f'SELECT COUNT(*) FROM `{name}`')[0][0]
            print(f'  - {name}: {count} строк')

        # 2. Колонки-кандидаты во всей базе: планировка может лежать в таблице
        #    с ничего не говорящим именем.
        print('\n--- 2. Колонки, похожие на ссылку/файл/планировку ---')
        columns = _fetch(connection, """
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = :db
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """, db=database)

        candidates = [(t, c, d) for t, c, d in columns if COLUMN_HINTS.search(c)]
        if not candidates:
            print('  Ничего не найдено — планировок в реплике нет.')
        for table_name, column_name, data_type in candidates:
            print(f'  - {table_name}.{column_name} ({data_type})')
            try:
                rows = _fetch(connection, f"""
                    SELECT DISTINCT `{column_name}` FROM `{table_name}`
                    WHERE `{column_name}` IS NOT NULL AND `{column_name}` <> ''
                    LIMIT {SAMPLE_LIMIT}
                """)
                for row in rows:
                    value = str(row[0])
                    print(f'      пример: {value[:160]}')
                if not rows:
                    print('      (колонка есть, но пустая)')
            except Exception as exc:
                print(f'      не удалось прочитать: {exc}')

        # 3. Полная схема estate_sells: планировка чаще всего висит прямо на квартире.
        print('\n--- 3. Все колонки estate_sells ---')
        for row in _fetch(connection, 'SHOW COLUMNS FROM estate_sells'):
            print(f'  - {row[0]} ({row[1]})')

        # 4. Насколько flatClass годится как ключ планировки: сколько типов
        #    приходится на ЖК и сколько квартир закрывает один тип.
        print('\n--- 4. Типы планировок (flatClass) по ЖК ---')
        try:
            rows = _fetch(connection, """
                SELECT h.complex_name,
                       COUNT(DISTINCT s.flatClass) AS layout_types,
                       COUNT(*) AS units
                FROM estate_sells s
                JOIN estate_houses h ON h.id = s.house_id
                WHERE s.estate_sell_category = 'flat'
                GROUP BY h.complex_name
                ORDER BY units DESC
            """)
            for complex_name, layout_types, units in rows:
                per_type = units / layout_types if layout_types else 0
                print(f'  - {complex_name}: {layout_types} типов на {units} квартир '
                      f'(~{per_type:.0f} квартир на тип)')
            empty = _fetch(connection, """
                SELECT COUNT(*) FROM estate_sells
                WHERE estate_sell_category = 'flat'
                  AND (flatClass IS NULL OR flatClass = '')
            """)[0][0]
            print(f'  Квартир без flatClass: {empty}')
        except Exception as exc:
            print(f'  Не удалось посчитать: {exc}')


if __name__ == '__main__':
    main()

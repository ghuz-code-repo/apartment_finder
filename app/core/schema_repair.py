"""Приведение уже существующих таблиц main_app.db к текущим моделям.

`db.create_all()` умеет только создавать недостающие таблицы — существующие он
не трогает. Поэтому база, созданная до правки модели, продолжает жить со старой
схемой, и приложение падает на ограничении, которого в коде давно нет.
Здесь такие расхождения снимаются на старте, до первого запроса.

Каждая проверка идемпотентна: на уже починенной базе она делает один SELECT из
sqlite_master и выходит.
"""

import logging

from sqlalchemy import MetaData, inspect, text

logger = logging.getLogger(__name__)

_TABLE = 'cancellation_registry'
_COLUMN = 'estate_sell_id'
_INDEX = 'ix_cancellation_registry_estate_sell_id'


def _stale_unique(inspector):
    """UNIQUE-индексы и UNIQUE-ограничения ровно по одной колонке _COLUMN.

    Ограничение попадает в один из двух списков в зависимости от того, как его
    когда-то создали: `unique=True` рядом с `index=True` даёт отдельный
    UNIQUE INDEX, `unique=True` без индекса — inline UNIQUE в DDL таблицы.
    """
    indexes = [
        idx['name'] for idx in inspector.get_indexes(_TABLE)
        if idx.get('name') and idx.get('unique')
        and list(idx.get('column_names') or []) == [_COLUMN]
    ]
    constraints = [
        con.get('name') for con in inspector.get_unique_constraints(_TABLE)
        if list(con.get('column_names') or []) == [_COLUMN]
    ]
    return indexes, constraints


def _rebuild_without_unique(engine):
    """Пересобирает таблицу по текущей модели: SQLite не умеет DROP CONSTRAINT."""
    from app.models.registry_models import CancellationRegistry

    table = CancellationRegistry.__table__
    staging = MetaData()
    tmp_name = f'{_TABLE}__rebuild'
    tmp_table = table.to_metadata(staging, name=tmp_name)
    # Индексы модели носят имена итоговой таблицы и столкнулись бы с индексами
    # ещё живого оригинала. Создаём их вручную после переименования.
    tmp_table.indexes.clear()

    existing = {col['name'] for col in inspect(engine).get_columns(_TABLE)}
    carried = [col.name for col in table.columns if col.name in existing]
    columns_sql = ', '.join(f'"{name}"' for name in carried)

    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{tmp_name}"'))
        tmp_table.create(bind=conn)
        conn.execute(text(
            f'INSERT INTO "{tmp_name}" ({columns_sql}) SELECT {columns_sql} FROM "{_TABLE}"'
        ))
        conn.execute(text(f'DROP TABLE "{_TABLE}"'))
        conn.execute(text(f'ALTER TABLE "{tmp_name}" RENAME TO "{_TABLE}"'))
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS "{_INDEX}" ON "{_TABLE}" ("{_COLUMN}")'
        ))


def repair_cancellation_registry(engine):
    """Снимает устаревший UNIQUE с cancellation_registry.estate_sell_id.

    Один объект расторгается несколько раз, поэтому в модели уникальности нет.
    Но базы, созданные до её удаления, всё ещё отвергают вторую запись по тому
    же объекту с 'UNIQUE constraint failed'.

    Возвращает True, если схему пришлось править.
    """
    inspector = inspect(engine)
    if not inspector.has_table(_TABLE):
        return False

    indexes, constraints = _stale_unique(inspector)
    if not indexes and not constraints:
        return False

    if constraints or engine.dialect.name == 'sqlite':
        _rebuild_without_unique(engine)
    else:
        with engine.begin() as conn:
            for name in indexes:
                conn.execute(text(f'DROP INDEX "{name}"'))
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "{_INDEX}" ON "{_TABLE}" ("{_COLUMN}")'
            ))

    logger.info("[SCHEMA] %s.%s: снято устаревшее ограничение UNIQUE", _TABLE, _COLUMN)
    return True


def repair_schema(db):
    """Все проверки схемы, которые нужно прогнать после db.create_all().

    Ошибки не пробрасываются: неудавшийся ремонт не должен ронять сервис —
    он лишь оставляет прежнее поведение, о котором сказано в логе.
    """
    try:
        if repair_cancellation_registry(db.engine):
            print("[SETUP] Схема cancellation_registry обновлена: UNIQUE снят")
    except Exception as exc:
        logger.warning("[SCHEMA] Не удалось починить %s: %s", _TABLE, exc)
        print(f"[SETUP] Warning: ремонт схемы {_TABLE} не выполнен: {exc}")

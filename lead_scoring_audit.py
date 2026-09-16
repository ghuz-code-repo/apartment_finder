"""Аудит данных для модели оценки входящих заявок (лид-скоринг).

Отвечает на вопрос, стоит ли строить модель, до того как её строить:
сколько истории, какая конверсия, различаются ли каналы и проекты, и насколько
простая модель обыгрывает правило «канал + проект».

Скрипт только читает MySQL витрины Macro. В отчёт попадают агрегаты — ни ФИО,
ни телефонов клиентов в нём нет, его можно пересылать.

Запуск на сервере:
    docker compose exec finder python lead_scoring_audit.py
    docker compose exec finder python lead_scoring_audit.py --horizon 90 --since 2023-01-01

Отчёт печатается и сохраняется в instance/lead_scoring_audit_<дата>.md.

Главное правило, на котором всё построено: признаки берутся только те, что
известны в момент поступления заявки. Поля, заполняемые позже (дом сделки,
сумма, текущий статус, первая встреча), модель видеть не должна — иначе на
истории она «угадывает» исход по его же следам и бесполезна на новых лидах.
"""

import argparse
import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect, text

STATUS_BOOKING = 30
STATUS_DEALS = (50, 53, 100)  # 52 «Маркетинговая сделка» — не продажа
STATUS_NONTARGET = 3
TOP_VALUES = 40          # сколько значений категории держать, остальное — «прочее»
MIN_GROUP = 50           # меньше заявок в группе — конверсия ничего не говорит
PROBE_TABLES = {
    'estate_buys': ['id', 'estate_buy_id', 'created_at', 'type', 'category', 'status',
                    'contacts_id', 'contacts_buy_type', 'is_primary_request', 'departments_id',
                    'channel_type', 'channel_name', 'channel_medium', 'utm_source', 'utm_medium',
                    'utm_campaign', 'first_complex_interest', 'first_house_interest', 'house_id',
                    'contacts_mediator_id', 'mediator_agency_id', 'advertising_channel_id',
                    'call_center_manager_id'],
    'estate_buys_statuses_log': ['estate_buy_id', 'log_date', 'status_from', 'status_to',
                                 'status_to_name'],
    'estate_buys_utm_history': ['estate_buy_id', 'created_at', 'is_first_attribution',
                                'channel_type', 'channel_name', 'utm_source', 'utm_medium',
                                'utm_campaign'],
    'estate_houses': ['id', 'house_id', 'complex_id', 'complex_name'],
    'calls': ['estate_id', 'call_date', 'direction', 'duration', 'is_hidden'],
    'tasks': ['id', 'estate_id', 'contacts_id', 'date_added', 'date_finish', 'custom_type',
              'custom_type_name', 'is_closed', 'manager_id'],
    'estate_meetings': ['estate_buy_id', 'meeting_date', 'no_meeting', 'complex_id', 'house_id'],
}


class Report:
    def __init__(self):
        self.lines = []

    def h(self, title):
        self.lines += ['', f'## {title}', '']
        print(f'\n== {title}', flush=True)

    def p(self, line=''):
        self.lines.append(line)

    def table(self, df):
        if df is None or df.empty:
            self.p('_нет данных_')
            return
        cols = list(df.columns)
        self.p('| ' + ' | '.join(str(c) for c in cols) + ' |')
        self.p('|' + '---|' * len(cols))
        for row in df.itertuples(index=False):
            self.p('| ' + ' | '.join(_fmt(v) for v in row) + ' |')

    def text(self):
        return '\n'.join(self.lines) + '\n'


def _to_datetime(series):
    # MySQL отдаёт datetime, но строки с долями секунд и без них в одной
    # колонке pandas без format='mixed' не разбирает.
    return pd.to_datetime(series, format='mixed', errors='coerce')


def _fmt(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return '—'
    if isinstance(value, float):
        # Метрики качества (ROC-AUC 0.713) теряют смысл при одном знаке.
        if abs(value) < 1:
            return f'{value:.3f}'
        return f'{value:,.1f}'.replace(',', ' ')
    if isinstance(value, (int, np.integer)):
        return f'{value:,}'.replace(',', ' ')
    return str(value).replace('|', '/')


def _mask(value):
    """В channel_name бывают номера телефонов линий — длинные цифры скрываем."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return value
    return re.sub(r'\d{5,}', lambda m: m.group(0)[:3] + '…', str(value))


def pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


# --- Загрузка ---

def probe_schema(engine, report):
    report.h('1. Какие таблицы и поля доступны')
    insp = inspect(engine)
    available = {}
    rows = []
    for table, wanted in PROBE_TABLES.items():
        try:
            present = {c['name'] for c in insp.get_columns(table)}
        except Exception:
            present = set()
        available[table] = present
        missing = [c for c in wanted if c not in present]
        rows.append({'таблица': table,
                     'доступна': 'да' if present else 'НЕТ',
                     'нужных полей': f'{len(wanted) - len(missing)} из {len(wanted)}',
                     'нет полей': ', '.join(missing) if present else '—'})
    report.table(pd.DataFrame(rows))
    return available


def load_leads(engine, cols, since):
    wanted = [c for c in PROBE_TABLES['estate_buys'] if c in cols]
    sql = f"SELECT {', '.join(wanted)} FROM estate_buys WHERE created_at IS NOT NULL"
    params = {}
    if since:
        sql += ' AND created_at >= :since'
        params['since'] = since
    df = pd.read_sql(text(sql), engine, params=params)
    df['created_at'] = _to_datetime(df['created_at'])
    return df


def load_first_status(engine, cols, statuses, only_forward_booking=False):
    """Первая дата перехода в статус(ы) по каждой заявке."""
    if 'status_to' in cols:
        cond = f"status_to IN ({', '.join(str(s) for s in statuses)})"
        if only_forward_booking and 'status_from' in cols:
            # Возврат сделки в бронь постановкой брони не считается.
            cond += f' AND status_from < {STATUS_BOOKING}'
    else:
        names = {30: 'Бронь', 50: 'Сделка в работе', 53: 'Сделка в работе', 100: 'Сделка проведена'}
        cond = "status_to_name IN ({})".format(', '.join(f"'{names[s]}'" for s in statuses if s in names))
    sql = (f'SELECT estate_buy_id, MIN(log_date) AS first_date FROM estate_buys_statuses_log '
           f'WHERE {cond} AND log_date IS NOT NULL GROUP BY estate_buy_id')
    df = pd.read_sql(text(sql), engine)
    return pd.Series(_to_datetime(df['first_date']).values, index=df['estate_buy_id'])


def load_first_touch_utm(engine, cols):
    if not {'estate_buy_id', 'is_first_attribution'} <= cols:
        return None
    fields = [c for c in ('channel_type', 'channel_name', 'utm_source', 'utm_medium', 'utm_campaign')
              if c in cols]
    sql = (f"SELECT estate_buy_id, {', '.join(fields)} FROM estate_buys_utm_history "
           f"WHERE is_first_attribution = 1")
    df = pd.read_sql(text(sql), engine).drop_duplicates('estate_buy_id')
    return df.set_index('estate_buy_id')


def load_calls(engine, cols):
    if not {'estate_id', 'call_date'} <= cols:
        return None
    hidden = ' AND (is_hidden IS NULL OR is_hidden = 0)' if 'is_hidden' in cols else ''
    direction = " AND direction IN ('in', 'out')" if 'direction' in cols else ''
    talk = 'MIN(CASE WHEN duration >= 30 THEN call_date END)' if 'duration' in cols else 'NULL'
    sql = (f'SELECT estate_id, MIN(call_date) AS first_call, {talk} AS first_talk FROM calls '
           f'WHERE estate_id IS NOT NULL{hidden}{direction} GROUP BY estate_id')
    df = pd.read_sql(text(sql), engine)
    df['first_call'] = _to_datetime(df['first_call'])
    df['first_talk'] = _to_datetime(df['first_talk'])
    return df.set_index('estate_id')


# --- Признаки ---

def build_features(leads, houses, first_touch, calls, horizon_days):
    df = leads.copy()

    # Проект интереса: комплекс, иначе дом интереса. Дом сделки не берём —
    # он появляется только с брони и выдал бы исход.
    complex_names = houses.dropna(subset=['complex_id']).drop_duplicates('complex_id') \
        .set_index('complex_id')['complex_name'] if 'complex_id' in houses else pd.Series(dtype=object)
    house_names = houses.dropna(subset=['house_id']).drop_duplicates('house_id') \
        .set_index('house_id')['complex_name'] if 'house_id' in houses else pd.Series(dtype=object)
    project = pd.Series(np.nan, index=df.index, dtype=object)
    if 'first_complex_interest' in df:
        project = df['first_complex_interest'].map(complex_names)
    if 'first_house_interest' in df:
        project = project.fillna(df['first_house_interest'].map(house_names))
    df['project'] = project

    # Источник — по первому касанию, если история UTM есть: поля в estate_buys
    # перезаписываются последним действием и могут «знать» о будущем.
    df['utm_changed_later'] = np.nan
    if first_touch is not None and 'estate_buy_id' in df:
        # История UTM ссылается на второй ключ заявки — estate_buy_id.
        # Если история у заявки есть, берём первое касание даже пустым: пустой
        # utm при поступлении — тоже факт, а подстановка из estate_buys
        # протащила бы значение, записанное позже.
        has_history = df['estate_buy_id'].isin(first_touch.index)
        for col in ('channel_type', 'channel_name', 'utm_source', 'utm_medium', 'utm_campaign'):
            if col not in first_touch:
                continue
            first = df['estate_buy_id'].map(first_touch[col]).replace('', np.nan)
            if col in df:
                if col == 'utm_source':
                    stored = df[col].replace('', np.nan)
                    differs = (first.fillna('') != stored.fillna('')).astype(float)
                    df['utm_changed_later'] = differs.where(has_history)
                df[col] = first.where(has_history, df[col])
            else:
                df[col] = first

    df['is_agent'] = df['contacts_mediator_id'].fillna(0).gt(0).astype(int) \
        if 'contacts_mediator_id' in df else 0
    df['hour'] = df['created_at'].dt.hour
    df['weekday'] = df['created_at'].dt.weekday
    df['month'] = df['created_at'].dt.month

    # История контакта на момент заявки: сколько было заявок и была ли бронь
    # до этой даты. Только прошлое — будущие заявки того же клиента не видим.
    df = df.sort_values('created_at')
    df['prior_leads'] = 0
    df['days_since_prior'] = np.nan
    df['prior_booked'] = 0
    if 'contacts_id' in df:
        has_contact = df['contacts_id'].fillna(0).gt(0)
        part = df[has_contact]
        contact = part['contacts_id']
        df.loc[has_contact, 'prior_leads'] = part.groupby(contact).cumcount()
        prev = part.groupby(contact)['created_at'].shift()
        df.loc[has_contact, 'days_since_prior'] = (part['created_at'] - prev).dt.days
        # Самая ранняя бронь по предыдущим заявкам контакта — и была ли она
        # раньше этой заявки. Без apply по группам: контактов сотни тысяч.
        earlier = part.groupby(contact)['booking_date'].shift()
        earlier_min = earlier.groupby(contact).cummin()
        df.loc[has_contact, 'prior_booked'] = (earlier_min < part['created_at']).astype(int)

    # Метки: бронь / сделка в пределах горизонта от создания.
    horizon = pd.Timedelta(days=horizon_days)
    df['days_to_booking'] = (df['booking_date'] - df['created_at']).dt.total_seconds() / 86400
    df['booked'] = (df['days_to_booking'].between(-1, horizon_days)).astype(int)
    df['days_to_deal'] = (df['deal_date'] - df['created_at']).dt.total_seconds() / 86400
    df['dealt'] = (df['days_to_deal'].between(-1, horizon_days)).astype(int)
    # Заявки моложе горизонта ещё не успели дойти до брони — в метки не берём.
    df['labeled'] = df['created_at'] <= df['created_at'].max() - horizon

    # Ранние сигналы (первые 24 часа) — для второй версии модели.
    df['call_24h'] = 0
    df['talk_24h'] = 0
    df['response_hours'] = np.nan
    if calls is not None and 'id' in df:
        first_call = df['id'].map(calls['first_call'])
        first_talk = df['id'].map(calls['first_talk'])
        delay = (first_call - df['created_at']).dt.total_seconds() / 3600
        talk_delay = (first_talk - df['created_at']).dt.total_seconds() / 3600
        df['call_24h'] = delay.le(24).astype(int)
        df['talk_24h'] = talk_delay.le(24).astype(int)
        df['response_hours'] = delay.clip(lower=0).where(delay.le(24))
    return df


CATEGORICAL = ['channel_type', 'channel_name', 'channel_medium', 'utm_source', 'utm_medium',
               'utm_campaign', 'project', 'category', 'departments_id', 'advertising_channel_id',
               'contacts_buy_type', 'mediator_agency_id']
NUMERIC = ['is_primary_request', 'is_agent', 'hour', 'weekday', 'month', 'prior_leads',
           'days_since_prior', 'prior_booked']
EARLY = ['call_24h', 'talk_24h', 'response_hours']
LAST_TOUCH_UTM = ['utm_source', 'utm_medium', 'utm_campaign']

# Входящие маркетинговые лиды. office и служебные каналы «Бронь»/«Клон» —
# заявки, которые менеджер заводит под уже идущую продажу: оценивать их нечего,
# а в обучении они учат модель узнавать оформление брони, а не интерес клиента.
INCOMING_CHANNEL_TYPES = ('www', 'calls', 'call', 'messenger')
OPERATIONAL_CHANNEL_NAMES = ('Бронь', 'Клон')

# Что предсказываем. Колонки booked/days_to_booking внутри скрипта означают
# «цель», подписи в отчёте берутся отсюда.
TARGETS = {
    'booking': {'what': 'бронь', 'many': 'броней', 'reached': 'Дошли до брони',
                'status': STATUS_BOOKING},
    'nontarget': {'what': 'нецелевой', 'many': 'нецелевых', 'reached': 'Признаны нецелевыми',
                  'status': STATUS_NONTARGET},
}
LABEL = TARGETS['booking']


# --- Разделы отчёта ---

def section_volume(df, report, horizon):
    report.h('2. Объём истории и конверсия')
    labeled = df[df['labeled']]
    report.p(f"- Заявок в выборке: **{_fmt(len(df))}**, период "
             f"{df['created_at'].min():%d.%m.%Y} — {df['created_at'].max():%d.%m.%Y}")
    report.p(f"- С известным исходом (старше {horizon} дней): **{_fmt(len(labeled))}**")
    report.p(f"- {LABEL['reached']} за {horizon} дней: **{_fmt(int(labeled['booked'].sum()))}** "
             f"({pct(labeled['booked'].sum(), len(labeled))}%)")
    report.p(f"- Дошли до сделки за {horizon} дней: **{_fmt(int(labeled['dealt'].sum()))}** "
             f"({pct(labeled['dealt'].sum(), len(labeled))}%)")
    if 'status' in df:
        report.p(f"- Сейчас в статусе «Нецелевой»: {pct((df['status'] == STATUS_NONTARGET).sum(), len(df))}%")
    report.p('')
    positives = labeled['booked'].sum()
    verdict = ('достаточно для модели' if positives >= 2000 else
               'хватит на простую модель, результат будет шумным' if positives >= 500 else
               'мало — модель будет ненадёжной, лучше правила')
    report.p(f"**Оценка объёма:** {_fmt(int(positives))} {LABEL['many']} в обучающей истории — {verdict}.")

    monthly = df.groupby(df['created_at'].dt.to_period('M')).agg(
        заявок=('booked', 'size'), целевых_за_горизонт=('booked', 'sum'),
        с_исходом=('labeled', 'sum')).reset_index()
    monthly['конверсия_%'] = np.where(monthly['с_исходом'] > 0,
                                      (monthly['целевых_за_горизонт'] * 100 / monthly['заявок']).round(1), np.nan)
    monthly = monthly.rename(columns={'created_at': 'месяц'})
    monthly['месяц'] = monthly['месяц'].astype(str)
    report.p('')
    report.p('По месяцам (конверсия только для месяцев с известным исходом):')
    report.p('')
    report.table(monthly.drop(columns=['с_исходом']).tail(36))


def section_timing(df, report):
    report.h(f"3. Через сколько наступает «{LABEL['what']}»")
    days = df['days_to_booking'].dropna()
    days = days[days >= -1]
    if days.empty:
        report.p(f"_{LABEL['many']} не найдено_")
        return
    rows = [{'показатель': f"{q}% {LABEL['many']} — не позже, дней", 'значение': float(days.quantile(q / 100))}
            for q in (50, 75, 90, 95)]
    rows += [{'показатель': f"доля {LABEL['many']} в первые {d} дней, %", 'значение': pct((days <= d).sum(), len(days))}
             for d in (7, 30, 60, 90, 180)]
    report.table(pd.DataFrame(rows))
    report.p('')
    report.p('Горизонт метки стоит выбирать так, чтобы в него попадало 85–90% ' + LABEL['many'] + '.')


def section_fill(df, report):
    report.h('4. Заполненность признаков на момент заявки')
    rows = []
    for col in CATEGORICAL + ['is_primary_request', 'contacts_id', 'first_complex_interest',
                              'first_house_interest']:
        if col not in df:
            rows.append({'поле': col, 'заполнено_%': None, 'уникальных': None})
            continue
        series = df[col]
        filled = series.notna() & (series.astype(str).str.strip() != '') & (series.astype(str) != '0')
        rows.append({'поле': col, 'заполнено_%': pct(filled.sum(), len(df)),
                     'уникальных': int(series[filled].nunique())})
    rows.append({'поле': 'project (итог по интересу)', 'заполнено_%': pct(df['project'].notna().sum(), len(df)),
                 'уникальных': int(df['project'].nunique())})
    report.table(pd.DataFrame(rows))
    changed = df['utm_changed_later'].dropna()
    if not changed.empty:
        report.p('')
        report.p(f'utm_source в заявке отличается от первого касания у **{pct(changed.sum(), len(changed))}%** '
                 f'заявок — поле перезаписывается последним действием, поэтому для модели берётся первое касание.')


def section_segments(df, report):
    report.h('5. Различается ли конверсия по признакам')
    labeled = df[df['labeled']]
    base = labeled['booked'].mean() * 100 if len(labeled) else 0
    report.p(f"Средняя доля «{LABEL['what']}»: **{base:.1f}%**." f' Чем сильнее группы расходятся со средней, '
             f'тем больше признак даёт модели.')
    segments = [('channel_type', 'Тип канала'), ('project', 'Проект интереса'),
                ('utm_source', 'utm_source (первое касание)'), ('channel_name', 'Канал'),
                ('is_primary_request', 'Первичная заявка'), ('is_agent', 'Агентская'),
                ('prior_booked', 'Раньше уже бронировал'), ('weekday', 'День недели')]
    for col, title in segments:
        if col not in labeled:
            continue
        values = labeled[col].map(_mask) if col == 'channel_name' else labeled[col]
        # К строке приводим всё: числа и «(пусто)» в одной группировке не сортируются.
        values = values.astype(object).where(values.notna(), '(пусто)').astype(str)
        g = labeled.assign(_v=values).groupby('_v').agg(
            заявок=('booked', 'size'), цель=('booked', 'sum'), сделок=('dealt', 'sum'))
        g = g[g['заявок'] >= MIN_GROUP].sort_values('заявок', ascending=False).head(15)
        if g.empty:
            continue
        g['цель_%'] = (g['цель'] * 100 / g['заявок']).round(1)
        g['сделка_%'] = (g['сделок'] * 100 / g['заявок']).round(1)
        g['к_средней'] = (g['цель_%'] / base).round(2) if base else np.nan
        report.p('')
        report.p(f'**{title}** (группы от {MIN_GROUP} заявок):')
        report.p('')
        report.table(g.reset_index().rename(columns={'_v': 'значение'}))

    if labeled['call_24h'].sum():
        report.p('')
        report.p('**Скорость реакции** (по звонкам, привязанным к заявке):')
        report.p('')
        bins = pd.cut(labeled['response_hours'], [-0.01, 0.25, 1, 4, 24],
                      labels=['до 15 мин', '15–60 мин', '1–4 ч', '4–24 ч'])
        g = labeled.assign(_v=bins.cat.add_categories('нет звонка за сутки').fillna('нет звонка за сутки')) \
            .groupby('_v', observed=False).agg(заявок=('booked', 'size'), цель=('booked', 'sum'))
        g['цель_%'] = (g['цель'] * 100 / g['заявок'].replace(0, np.nan)).round(1)
        report.table(g.reset_index().rename(columns={'_v': 'первый звонок'}))


def _prepare_matrix(train, test, features):
    X_train, X_test = train[features].copy(), test[features].copy()
    for col in features:
        if col in CATEGORICAL:
            tr = X_train[col].astype(str).where(X_train[col].notna(), '(пусто)')
            te = X_test[col].astype(str).where(X_test[col].notna(), '(пусто)')
            keep = tr.value_counts()
            keep = set(keep[keep >= 30].head(TOP_VALUES).index)
            tr = tr.where(tr.isin(keep), 'прочее')
            te = te.where(te.isin(keep), 'прочее')
            cats = sorted(set(tr) | {'прочее'})
            X_train[col] = pd.Categorical(tr, categories=cats)
            X_test[col] = pd.Categorical(te, categories=cats)
        else:
            X_train[col] = pd.to_numeric(X_train[col], errors='coerce').astype(float)
            X_test[col] = pd.to_numeric(X_test[col], errors='coerce').astype(float)
    return X_train, X_test


def _capture(y_true, scores, share):
    order = np.argsort(-scores)
    top = order[:max(1, int(len(order) * share))]
    total = y_true.sum()
    return round(y_true[top].sum() * 100 / total, 1) if total else None


def section_model(df, report, has_first_touch, drop_features=()):
    report.h(f"6. Базовая модель: насколько предсказуем «{LABEL['what']}»")
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.inspection import permutation_importance
        from sklearn.metrics import average_precision_score, roc_auc_score
    except ImportError:
        report.p('_scikit-learn не установлен — раздел пропущен_')
        return

    labeled = df[df['labeled']].sort_values('created_at')
    if labeled['booked'].sum() < 100 or len(labeled) < 2000:
        report.p('_Слишком мало данных для проверки модели._')
        return

    # Проверка «из прошлого в будущее»: учим на ранних заявках, проверяем на
    # последней четверти. Случайное перемешивание завысило бы качество.
    cut = int(len(labeled) * 0.75)
    train, test = labeled.iloc[:cut], labeled.iloc[cut:]
    report.p(f"Обучение: {train['created_at'].min():%d.%m.%Y}–{train['created_at'].max():%d.%m.%Y} "
             f"({_fmt(len(train))} заявок), проверка: {test['created_at'].min():%d.%m.%Y}–"
             f"{test['created_at'].max():%d.%m.%Y} ({_fmt(len(test))} заявок).")
    report.p('')
    y_train, y_test = train['booked'].values, test['booked'].values

    rows = []
    # Правило для сравнения: средняя конверсия связки «канал + проект» на обучении.
    key_tr = train['channel_type'].astype(str) + '|' + train['project'].astype(str)
    key_te = test['channel_type'].astype(str) + '|' + test['project'].astype(str)
    stats = pd.DataFrame({'k': key_tr, 'y': y_train}).groupby('k')['y'].agg(['sum', 'count'])
    prior = y_train.mean()
    smoothed = (stats['sum'] + prior * 50) / (stats['count'] + 50)
    rule_scores = key_te.map(smoothed).fillna(prior).values
    rows.append(_metrics_row('Правило «канал + проект»', y_test, rule_scores, roc_auc_score,
                             average_precision_score))

    # Без истории UTM в estate_buys лежит последнее касание — оно пишется в том
    # числе действиями менеджера после поступления и выдаёт исход.
    excluded = [] if has_first_touch else [c for c in LAST_TOUCH_UTM if c in labeled]
    if excluded:
        report.p('**Внимание:** истории UTM нет, поля ' + ', '.join(excluded) + ' в estate_buys '
                 'перезаписываются последним действием — в модель не включены.')
        report.p('')
    if drop_features:
        report.p('Исключены вручную (подозрение на утечку): ' + ', '.join(drop_features) + '.')
        report.p('')
        excluded = excluded + [c for c in drop_features if c not in excluded]

    suspects = _leak_suspects(train, test, [c for c in CATEGORICAL + NUMERIC + EARLY
                                            if c in labeled and c not in excluded], roc_auc_score)

    models = {}
    has_calls = bool(labeled['call_24h'].sum())
    for name, extra in (('Модель: данные при поступлении', []),
                        ('Модель: + сигналы первых суток', EARLY)):
        if extra and not has_calls:
            # Без звонков вторая модель повторила бы первую строку.
            continue
        features = [c for c in CATEGORICAL + NUMERIC + extra if c in labeled and c not in excluded]
        X_train, X_test = _prepare_matrix(train, test, features)
        model = HistGradientBoostingClassifier(categorical_features='from_dtype', max_iter=300,
                                               learning_rate=0.05, early_stopping=True,
                                               random_state=42)
        model.fit(X_train, y_train)
        scores = model.predict_proba(X_test)[:, 1]
        rows.append(_metrics_row(name, y_test, scores, roc_auc_score, average_precision_score))
        models[name] = (model, X_test, features)

    rows.append({'вариант': 'Случайный порядок', 'ROC-AUC': 0.5,
                 'PR-AUC': round(float(y_test.mean()), 3),
                 'цели в топ-10%': 10.0, 'в топ-20%': 20.0, 'в топ-30%': 30.0})
    report.table(pd.DataFrame(rows))
    report.p('')
    report.p('Как читать: «в топ-20%» — какую долю будущих случаев цели модель ставит в пятую часть '
             'заявок с самой высокой оценкой. 20 — не лучше случайного, 40+ — заметная польза, '
             '60+ — сильная модель.')

    best_auc = max(r['ROC-AUC'] for r in rows)
    if suspects or best_auc > 0.95:
        report.p('')
        report.p('**⚠ Подозрение на утечку будущего.** Реальные лиды так точно не предсказываются: '
                 'скорее всего, признак заполняется после продвижения заявки. Результаты модели '
                 'выше недостоверны, пока признак не исключён.')
        if suspects:
            report.p('')
            report.table(pd.DataFrame(suspects))

    name = 'Модель: данные при поступлении'
    model, X_test, features = models[name]
    sample = X_test.sample(min(len(X_test), 20000), random_state=42)
    y_sample = test.loc[sample.index, 'booked'].values
    imp = permutation_importance(model, sample, y_sample, scoring='roc_auc', n_repeats=3,
                                 random_state=42)
    importance = pd.DataFrame({'признак': features, 'вклад_в_AUC': imp.importances_mean.round(4)}) \
        .sort_values('вклад_в_AUC', ascending=False)
    report.p('')
    report.p('**Какие признаки работают** (падение ROC-AUC, если признак перемешать):')
    report.p('')
    report.table(importance)


def _leak_suspects(train, test, features, roc_auc_score, threshold=0.9):
    """Признаки, которые в одиночку почти идеально угадывают бронь.

    Для категории оценка — конверсия её значения на обучении, для числа — само
    значение (в обе стороны). Честный признак входящей заявки до 0.9 не дотягивает.
    """
    y_train, y_test = train['booked'].values, test['booked'].values
    if y_test.min() == y_test.max():
        return []
    prior = y_train.mean()
    suspects = []
    for col in features:
        if col in CATEGORICAL:
            tr = train[col].astype(str)
            stats = pd.DataFrame({'v': tr, 'y': y_train}).groupby('v')['y'].agg(['sum', 'count'])
            rate = (stats['sum'] + prior * 20) / (stats['count'] + 20)
            scores = test[col].astype(str).map(rate).fillna(prior).values
        else:
            scores = pd.to_numeric(test[col], errors='coerce').fillna(-1).values
        try:
            auc = roc_auc_score(y_test, scores)
        except ValueError:
            continue
        auc = max(auc, 1 - auc)
        if auc >= threshold:
            suspects.append({'признак': col, 'ROC-AUC в одиночку': round(float(auc), 3)})
    return suspects


def _metrics_row(name, y, scores, roc_auc_score, average_precision_score):
    return {'вариант': name,
            'ROC-AUC': round(float(roc_auc_score(y, scores)), 3),
            'PR-AUC': round(float(average_precision_score(y, scores)), 3),
            'цели в топ-10%': _capture(y, scores, 0.1),
            'в топ-20%': _capture(y, scores, 0.2),
            'в топ-30%': _capture(y, scores, 0.3)}


def section_tasks(engine, available, report):
    """Заодно — ответ для воронки: какими типами задач назначают встречи."""
    if not {'custom_type', 'custom_type_name'} <= available.get('tasks', set()):
        return
    report.h('7. Типы задач в CRM (для этапа «Встреча назначена»)')
    df = pd.read_sql(text('SELECT custom_type, custom_type_name, COUNT(*) AS n FROM tasks '
                          'GROUP BY custom_type, custom_type_name ORDER BY n DESC'), engine)
    report.table(df.head(30))


def main():
    parser = argparse.ArgumentParser(description='Аудит данных для лид-скоринга')
    parser.add_argument('--horizon', type=int, default=60, help='горизонт метки, дней')
    parser.add_argument('--target', choices=sorted(TARGETS), default='booking',
                        help='что предсказывать: бронь или признание лида нецелевым')
    parser.add_argument('--exclude-walkins', action='store_true',
                        help='убрать самоприходы в офис: заявки без utm_source в первом касании')
    parser.add_argument('--since', help='брать заявки с даты YYYY-MM-DD')
    parser.add_argument('--out', help='куда сохранить отчёт (.md)')
    parser.add_argument('--incoming-only', action='store_true',
                        help='только входящие лиды: www, звонки, мессенджеры без «Бронь»/«Клон»')
    parser.add_argument('--new-clients-only', action='store_true',
                        help='без заявок клиентов, у которых уже была бронь: это оформление, а не новый лид')
    parser.add_argument('--exclude', default='',
                        help='признаки через запятую, которые не давать модели')
    args = parser.parse_args()
    global LABEL
    LABEL = TARGETS[args.target]

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    uri = os.environ.get('SOURCE_MYSQL_URI')
    if not uri:
        sys.exit('SOURCE_MYSQL_URI не задан')

    engine = create_engine(uri, pool_pre_ping=True)
    report = Report()
    report.p(f"# Аудит данных для лид-скоринга — {datetime.now():%d.%m.%Y %H:%M}")
    report.p('')
    report.p(f"Метка: «{LABEL['what']}» в течение {args.horizon} дней после создания заявки."
             + (' Без самоприходов в офис (пустой utm_source первого касания).' if args.exclude_walkins else '')
             + (f' Заявки с {args.since}.' if args.since else '')
             + (' Только входящие лиды (' + ', '.join(INCOMING_CHANNEL_TYPES) + '; без каналов '
                + ', '.join(OPERATIONAL_CHANNEL_NAMES) + ').' if args.incoming_only else '')
             + (' Только новые клиенты (без прошлых броней).' if args.new_clients_only else ''))

    available = probe_schema(engine, report)
    if not available.get('estate_buys') or not available.get('estate_buys_statuses_log'):
        report.p('')
        report.p('**Без estate_buys и лога статусов аудит невозможен.**')
    else:
        print('Загрузка заявок...', flush=True)
        leads = load_leads(engine, available['estate_buys'], args.since)
        print(f'  {len(leads)} заявок', flush=True)
        log_cols = available['estate_buys_statuses_log']
        booking = load_first_status(engine, log_cols, (STATUS_BOOKING,), only_forward_booking=True)
        deals = load_first_status(engine, log_cols, STATUS_DEALS)
        nontarget = load_first_status(engine, log_cols, (STATUS_NONTARGET,))             if args.target == 'nontarget' else None
        leads['booking_date'] = leads['id'].map(booking)
        leads['deal_date'] = leads['id'].map(deals)
        if 'type' in leads:
            # По документации type — buy|rent, но в витрине бывает living|comm.
            # Поэтому не оставляем «buy», а убираем только аренду.
            leads = leads[leads['type'] != 'rent']
        if leads.empty:
            sys.exit('После фильтров не осталось заявок — проверьте --since и поле type')

        houses_cols = [c for c in ('house_id', 'complex_id', 'complex_name')
                       if c in available.get('estate_houses', set())]
        houses = pd.read_sql(text(f"SELECT {', '.join(houses_cols)} FROM estate_houses"), engine) \
            if houses_cols else pd.DataFrame()
        print('Загрузка UTM и звонков...', flush=True)
        first_touch = load_first_touch_utm(engine, available.get('estate_buys_utm_history', set()))
        calls = load_calls(engine, available.get('calls', set()))

        df = build_features(leads, houses, first_touch, calls, args.horizon)
        if args.incoming_only:
            # Фильтр после признаков: канал берётся из первого касания, а история
            # контакта должна учитывать и служебные заявки.
            before = len(df)
            df = df[df['channel_type'].isin(INCOMING_CHANNEL_TYPES)
                    & ~df['channel_name'].isin(OPERATIONAL_CHANNEL_NAMES)]
            print(f'  входящих лидов: {len(df)} из {before}', flush=True)
        if args.exclude_walkins:
            before = len(df)
            source = df['utm_source'].astype(str).str.strip()
            df = df[df['utm_source'].notna() & (source != '') & (source != 'nan')]
            print(f'  без самоприходов: {len(df)} из {before}', flush=True)
        if args.target == 'nontarget':
            # Цель подменяется после признаков: история контакта (prior_booked)
            # по-прежнему считается по броням.
            days = (df['id'].map(nontarget) - df['created_at']).dt.total_seconds() / 86400
            df = df.assign(days_to_booking=days,
                           booked=days.between(-1, args.horizon).astype(int))
        if args.new_clients_only:
            before = len(df)
            df = df[df['prior_booked'] == 0]
            print(f'  новых клиентов: {len(df)} из {before}', flush=True)
        section_volume(df, report, args.horizon)
        section_timing(df, report)
        section_fill(df, report)
        section_segments(df, report)
        print('Обучение проверочной модели...', flush=True)
        drop = [c.strip() for c in args.exclude.split(',') if c.strip()]
        section_model(df, report, has_first_touch=first_touch is not None, drop_features=drop)
    section_tasks(engine, available, report)

    out = args.out or os.path.join('instance', f"lead_scoring_audit_{datetime.now():%Y-%m-%d}.md")
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(report.text())
    print(report.text())
    print(f'Отчёт сохранён: {out}', flush=True)


if __name__ == '__main__':
    main()

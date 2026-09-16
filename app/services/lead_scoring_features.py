# app/services/lead_scoring_features.py
"""Признаки для скоринга входящих лидов.

Один модуль и для обучения, и для оценки новых заявок. Если собирать признаки
в двух местах, они однажды разойдутся, и модель будет оценивать не то, на чём
училась, — без единой ошибки в логах.

Правила выведены из аудита данных (lead_scoring_audit.py):

* признаки — только известные в момент поступления заявки. Проект интереса,
  отдел, channel_medium, advertising_channel_id заполняются позже и выдавали
  исход, utm_medium ухудшал качество;
* источник — по первому касанию из estate_buys_utm_history: поля utm в самой
  заявке перезаписываются последним действием;
* оцениваются только входящие лиды новых клиентов. Служебные заявки («Бронь»,
  «Клон», офис), самоприходы (пустой utm) и заявки действующих клиентов
  модель не оценивает — там нечего предсказывать.
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

STATUS_BOOKING = 30
INCOMING_CHANNEL_TYPES = ('www', 'calls', 'call', 'messenger')
OPERATIONAL_CHANNEL_NAMES = ('Бронь', 'Клон')

LEAD_COLUMNS = ('id', 'estate_buy_id', 'created_at', 'type', 'category', 'contacts_id',
                'contacts_buy_type', 'is_primary_request', 'channel_type', 'channel_name',
                'utm_source', 'utm_campaign')
FIRST_TOUCH_COLUMNS = ('channel_type', 'channel_name', 'utm_source', 'utm_campaign')

CATEGORICAL = ['channel_type', 'channel_name', 'utm_source', 'utm_campaign', 'category',
               'contacts_buy_type']
NUMERIC = ['is_primary_request', 'hour', 'weekday', 'month', 'prior_leads', 'days_since_prior']

SKIP_REASONS = {
    'rent': 'аренда',
    'not_incoming': 'не входящий канал',
    'operational': 'служебная заявка',
    'walk_in': 'самоприход в офис',
    'existing_client': 'действующий клиент',
}

CHUNK = 5000


def _to_datetime(series):
    return pd.to_datetime(series, format='mixed', errors='coerce')


def _chunks(values):
    values = list(values)
    for start in range(0, len(values), CHUNK):
        yield values[start:start + CHUNK]


def _in_clause(column, values, prefix):
    """IN с именованными параметрами: значения не подставляются в текст запроса."""
    names = [f'{prefix}{i}' for i in range(len(values))]
    return f"{column} IN ({', '.join(':' + n for n in names)})", dict(zip(names, values))


def load_leads(engine, created_since=None, contact_ids=None, lead_ids=None):
    """Заявки витрины. Без условий — вся история (для обучения)."""
    base = f"SELECT {', '.join(LEAD_COLUMNS)} FROM estate_buys WHERE created_at IS NOT NULL"
    frames = []
    if contact_ids is not None or lead_ids is not None:
        column, values = ('contacts_id', contact_ids) if contact_ids is not None else ('id', lead_ids)
        for part in _chunks(sorted(set(v for v in values if v))):
            clause, params = _in_clause(column, part, 'k')
            frames.append(pd.read_sql(text(f'{base} AND {clause}'), engine, params=params))
    else:
        params = {}
        if created_since is not None:
            base += ' AND created_at >= :since'
            params['since'] = created_since
        frames.append(pd.read_sql(text(base), engine, params=params))

    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=list(LEAD_COLUMNS))
    df = pd.concat(frames, ignore_index=True).drop_duplicates('id')
    df['created_at'] = _to_datetime(df['created_at'])
    return df


def load_booking_dates(engine, lead_ids=None):
    """Первая постановка брони по заявке. Возврат сделки в бронь не считается."""
    sql = ('SELECT estate_buy_id, MIN(log_date) AS first_date FROM estate_buys_statuses_log '
           f'WHERE status_to = {STATUS_BOOKING} AND status_from < {STATUS_BOOKING} '
           'AND log_date IS NOT NULL')
    frames = []
    if lead_ids is None:
        frames.append(pd.read_sql(text(sql + ' GROUP BY estate_buy_id'), engine))
    else:
        for part in _chunks(sorted(set(lead_ids))):
            clause, params = _in_clause('estate_buy_id', part, 'b')
            frames.append(pd.read_sql(text(f'{sql} AND {clause} GROUP BY estate_buy_id'),
                                      engine, params=params))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=['estate_buy_id', 'first_date'])
    return pd.Series(_to_datetime(df['first_date']).values, index=df['estate_buy_id'])


def load_first_touch(engine, buy_keys=None):
    """Первое касание UTM, индекс — estate_buys.estate_buy_id."""
    sql = (f"SELECT estate_buy_id, {', '.join(FIRST_TOUCH_COLUMNS)} FROM estate_buys_utm_history "
           'WHERE is_first_attribution = 1')
    frames = []
    if buy_keys is None:
        frames.append(pd.read_sql(text(sql), engine))
    else:
        for part in _chunks(sorted(set(k for k in buy_keys if k))):
            clause, params = _in_clause('estate_buy_id', part, 'u')
            frames.append(pd.read_sql(text(f'{sql} AND {clause}'), engine, params=params))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=['estate_buy_id', *FIRST_TOUCH_COLUMNS])
    return df.drop_duplicates('estate_buy_id').set_index('estate_buy_id')


def build_frame(leads, booking_dates, first_touch):
    """Признаки на момент поступления каждой заявки.

    История контакта считается по всем переданным заявкам, поэтому при оценке
    новых заявок сюда передаются и прошлые заявки тех же контактов.
    """
    df = leads.copy()
    df['booking_date'] = df['id'].map(booking_dates)

    # Первое касание, если история есть: пустой utm при поступлении — тоже
    # факт, подставлять значение, записанное позже, нельзя.
    has_history = df['estate_buy_id'].isin(first_touch.index)
    for col in FIRST_TOUCH_COLUMNS:
        first = df['estate_buy_id'].map(first_touch[col]).replace('', np.nan)
        df[col] = first.where(has_history, df[col].replace('', np.nan))

    df['hour'] = df['created_at'].dt.hour
    df['weekday'] = df['created_at'].dt.weekday
    df['month'] = df['created_at'].dt.month

    df = df.sort_values(['created_at', 'id'])
    df['prior_leads'] = 0
    df['days_since_prior'] = np.nan
    df['prior_booked'] = 0
    has_contact = pd.to_numeric(df['contacts_id'], errors='coerce').fillna(0).gt(0)
    if has_contact.any():
        part = df[has_contact]
        contact = part['contacts_id']
        df.loc[has_contact, 'prior_leads'] = part.groupby(contact).cumcount()
        prev = part.groupby(contact)['created_at'].shift()
        df.loc[has_contact, 'days_since_prior'] = (part['created_at'] - prev).dt.days
        # Бронь по одной из прошлых заявок контакта — и раньше этой заявки.
        earlier = part.groupby(contact)['booking_date'].shift()
        earlier_min = earlier.groupby(contact).cummin()
        df.loc[has_contact, 'prior_booked'] = (earlier_min < part['created_at']).astype(int)

    df['skip_reason'] = skip_reasons(df)
    return df


def skip_reasons(df):
    """Почему заявку не оцениваем. None — оцениваем."""
    reasons = pd.Series(None, index=df.index, dtype=object)
    source = df['utm_source'].astype(str).str.strip()
    walk_in = df['utm_source'].isna() | source.isin(['', 'nan', 'None'])
    # У заявки одна причина — первая подошедшая по порядку: сначала то, что
    # следует из самой заявки, потом из истории клиента.
    rules = [
        ('rent', df['type'] == 'rent'),
        ('operational', df['channel_name'].isin(OPERATIONAL_CHANNEL_NAMES)),
        ('not_incoming', ~df['channel_type'].isin(INCOMING_CHANNEL_TYPES)),
        ('walk_in', walk_in),
        ('existing_client', df['prior_booked'] == 1),
    ]
    for code, mask in rules:
        reasons = reasons.mask(mask.fillna(False) & reasons.isna(), code)
    return reasons


def add_label(df, horizon_days):
    """Метка «бронь в течение horizon_days» и признак, что исход уже известен."""
    days = (df['booking_date'] - df['created_at']).dt.total_seconds() / 86400
    df['label'] = days.between(-1, horizon_days).astype(int)
    df['labeled'] = df['created_at'] <= df['created_at'].max() - pd.Timedelta(days=horizon_days)
    return df


def encode(df, vocab=None, top_values=40, min_count=30):
    """Матрица признаков. Словарь категорий строится на обучении и хранится
    вместе с моделью: при оценке незнакомое значение становится «прочее»."""
    X = pd.DataFrame(index=df.index)
    build = vocab is None
    vocab = {} if build else vocab
    for col in CATEGORICAL:
        values = df[col].astype(object).where(df[col].notna(), '(пусто)').astype(str)
        if build:
            counts = values.value_counts()
            vocab[col] = sorted(counts[counts >= min_count].head(top_values).index.tolist())
        allowed = set(vocab[col])
        values = values.where(values.isin(allowed), 'прочее')
        X[col] = pd.Categorical(values, categories=sorted(allowed | {'прочее'}))
    for col in NUMERIC:
        X[col] = pd.to_numeric(df[col], errors='coerce').astype(float)
    return X, vocab

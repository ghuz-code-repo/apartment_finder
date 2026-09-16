# app/services/lead_scoring_service.py
"""Скоринг входящих лидов — тестовый режим.

Модель оценивает вероятность, что новый входящий лид дойдёт до брони за
horizon дней. Оценки сохраняются и показываются на странице проверки, но в
работу колл-центра пока не попадают: сначала нужно убедиться на свежих лидах,
что группы A/B/C действительно различаются по броням.

Проверка качества устроена «из прошлого в будущее»: модель учится на ранних
заявках и оценивается на более поздних, которых не видела. Случайное
перемешивание завысило бы цифры — соседние по времени заявки похожи.
"""

import json
import os
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from flask import current_app

from app.core.extensions import db
from app.models.lead_scoring_models import LeadScore, LeadScoringModel
from . import lead_scoring_features as features

DEFAULT_HORIZON_DAYS = 180
TEST_SHARE = 0.2
# Группы по доле заявок с самой высокой оценкой на отложенном периоде.
GRADE_SHARES = (('A', 0.10), ('B', 0.20), ('C', 0.70))
CAPTURE_SHARES = (0.1, 0.2, 0.3)


def _engine():
    return db.engines['mysql_source']


def _artifact_dir():
    path = os.path.join(current_app.instance_path, 'lead_scoring')
    os.makedirs(path, exist_ok=True)
    return path


def _log(message):
    print(f"[{datetime.now():%H:%M:%S}] [LEAD SCORING] {message}", flush=True)


# --- Обучение ---

def _capture(labels, scores, share):
    """Какая доля всех броней попала в верхние share заявок по оценке."""
    total = labels.sum()
    if not total:
        return None
    top = np.argsort(-scores)[:max(1, int(len(scores) * share))]
    return round(float(labels[top].sum() * 100 / total), 1)


def _grade_thresholds(scores):
    """Пороги оценки для групп: A — верхние 10%, B — следующие 20%."""
    thresholds = []
    cumulative = 0.0
    for grade, share in GRADE_SHARES[:-1]:
        cumulative += share
        thresholds.append({'grade': grade, 'min_score': float(np.quantile(scores, 1 - cumulative))})
    thresholds.append({'grade': GRADE_SHARES[-1][0], 'min_score': float('-inf')})
    return thresholds


def grade_for(score, thresholds):
    for item in thresholds:
        if score >= item['min_score']:
            return item['grade']
    return thresholds[-1]['grade']


def _grade_stats(labels, scores, thresholds):
    grades = np.array([grade_for(s, thresholds) for s in scores])
    total_leads, total_booked = len(labels), labels.sum()
    stats = []
    for item in thresholds:
        mask = grades == item['grade']
        leads, booked = int(mask.sum()), int(labels[mask].sum())
        stats.append({
            'grade': item['grade'],
            'min_score': item['min_score'] if np.isfinite(item['min_score']) else None,
            'leads': leads,
            'leads_share': round(leads * 100 / total_leads, 1) if total_leads else None,
            'booked': booked,
            'booking_rate': round(booked * 100 / leads, 2) if leads else None,
            'bookings_share': round(booked * 100 / total_booked, 1) if total_booked else None,
        })
    return stats


def train(horizon_days=DEFAULT_HORIZON_DAYS, activate=True):
    """Обучает новую версию модели на всей истории витрины."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score

    engine = _engine()
    _log('Загрузка истории заявок...')
    leads = features.load_leads(engine)
    booking = features.load_booking_dates(engine)
    first_touch = features.load_first_touch(engine)
    _log(f'Заявок: {len(leads)}. Сборка признаков...')

    frame = features.add_label(features.build_frame(leads, booking, first_touch), horizon_days)
    population = frame[frame['skip_reason'].isna() & frame['labeled']].sort_values('created_at')
    if population['label'].sum() < 200:
        raise ValueError(f"Слишком мало броней для обучения: {int(population['label'].sum())}")

    cut = int(len(population) * (1 - TEST_SHARE))
    train_part, test_part = population.iloc[:cut], population.iloc[cut:]
    X_train, vocab = features.encode(train_part)
    X_test, _ = features.encode(test_part, vocab)
    y_train, y_test = train_part['label'].values, test_part['label'].values

    _log(f'Обучение: {len(train_part)} заявок, проверка: {len(test_part)}...')
    model = HistGradientBoostingClassifier(categorical_features='from_dtype', max_iter=300,
                                           learning_rate=0.05, early_stopping=True,
                                           random_state=42)
    model.fit(X_train, y_train)
    scores = model.predict_proba(X_test)[:, 1]
    thresholds = _grade_thresholds(scores)

    metrics = {
        'roc_auc': round(float(roc_auc_score(y_test, scores)), 3),
        'pr_auc': round(float(average_precision_score(y_test, scores)), 4),
        'base_rate': round(float(y_test.mean() * 100), 3),
        'capture': {f'{int(s * 100)}': _capture(y_test, scores, s) for s in CAPTURE_SHARES},
        'grades': _grade_stats(y_test, scores, thresholds),
        'skipped': {code: int(n) for code, n in frame['skip_reason'].value_counts().items()},
    }
    _log(f"ROC-AUC {metrics['roc_auc']}, броней в топ-20%: {metrics['capture']['20']}%")

    last = db.session.query(db.func.max(LeadScoringModel.version)).scalar() or 0
    version = last + 1
    path = os.path.join(_artifact_dir(), f'model_v{version}.joblib')
    joblib.dump({'model': model, 'vocab': vocab, 'categorical': features.CATEGORICAL,
                 'numeric': features.NUMERIC, 'thresholds': thresholds,
                 'horizon_days': horizon_days, 'version': version}, path)

    record = LeadScoringModel(
        version=version, artifact_path=path, horizon_days=horizon_days,
        train_from=train_part['created_at'].min().to_pydatetime(),
        train_to=train_part['created_at'].max().to_pydatetime(),
        test_from=test_part['created_at'].min().to_pydatetime(),
        test_to=test_part['created_at'].max().to_pydatetime(),
        train_rows=len(train_part), test_rows=len(test_part),
        train_positives=int(y_train.sum()), test_positives=int(y_test.sum()),
        metrics_json=json.dumps(metrics, ensure_ascii=False),
        grades_json=json.dumps([{**t, 'min_score': t['min_score'] if np.isfinite(t['min_score']) else None}
                                for t in thresholds]),
        features_json=json.dumps({'categorical': features.CATEGORICAL, 'numeric': features.NUMERIC,
                                  'vocab_sizes': {k: len(v) for k, v in vocab.items()}},
                                 ensure_ascii=False),
    )
    if activate:
        LeadScoringModel.query.update({LeadScoringModel.is_active: False})
        record.is_active = True
    db.session.add(record)
    db.session.commit()
    _log(f'Модель v{version} сохранена: {path}')
    return record


# --- Оценка новых заявок ---

def active_model():
    return LeadScoringModel.query.filter_by(is_active=True).first()


def _load_artifact(record):
    artifact = joblib.load(record.artifact_path)
    # В файле порог «ниже всех» записан как -inf, в JSON — как None.
    for item in artifact['thresholds']:
        if item['min_score'] is None:
            item['min_score'] = float('-inf')
    return artifact


def score_recent(days=3, record=None):
    """Оценивает заявки последних days дней, которые эта модель ещё не видела."""
    record = record or active_model()
    if not record:
        raise ValueError('Нет активной модели: сначала обучите её (python lead_scoring.py train)')

    engine = _engine()
    since = datetime.now() - timedelta(days=days)
    targets = features.load_leads(engine, created_since=since)
    if targets.empty:
        return {'scored': 0, 'skipped': 0, 'already': 0}

    known = {row[0] for row in db.session.query(LeadScore.estate_buy_id).filter(
        LeadScore.model_id == record.id, LeadScore.estate_buy_id.in_(targets['id'].tolist())).all()}
    targets = targets[~targets['id'].isin(known)]
    if targets.empty:
        return {'scored': 0, 'skipped': 0, 'already': len(known)}

    # История контакта нужна та же, что при обучении: прошлые заявки и брони.
    history = features.load_leads(engine, contact_ids=targets['contacts_id'].dropna().astype(int).tolist())
    leads = targets if history.empty else \
        pd.concat([history, targets], ignore_index=True).drop_duplicates('id')
    booking = features.load_booking_dates(engine, lead_ids=leads['id'].tolist())
    first_touch = features.load_first_touch(engine, buy_keys=targets['estate_buy_id'].tolist())
    frame = features.build_frame(leads, booking, first_touch)
    frame = frame[frame['id'].isin(targets['id'])]

    artifact = _load_artifact(record)
    scorable = frame[frame['skip_reason'].isna()]
    scores = {}
    if not scorable.empty:
        X, _ = features.encode(scorable, artifact['vocab'])
        scores = dict(zip(scorable['id'], artifact['model'].predict_proba(X)[:, 1]))

    rows = []
    for lead in frame.itertuples(index=False):
        score = scores.get(lead.id)
        rows.append(LeadScore(
            estate_buy_id=int(lead.id), model_id=record.id,
            lead_created_at=lead.created_at.to_pydatetime(),
            score=float(score) if score is not None else None,
            grade=grade_for(score, artifact['thresholds']) if score is not None else None,
            skip_reason=lead.skip_reason if score is None else None,
            channel_type=lead.channel_type if isinstance(lead.channel_type, str) else None,
            utm_source=str(lead.utm_source)[:255] if isinstance(lead.utm_source, str) else None,
        ))
    db.session.add_all(rows)
    db.session.commit()
    return {'scored': len(scores), 'skipped': len(rows) - len(scores), 'already': len(known)}


# --- Проверка на свежих лидах ---

def live_check(record, recent_limit=100):
    """Как группы оценённых лидов конвертируются в брони на деле.

    Горизонт модели — полгода, поэтому первые недели цифры предварительные:
    сравнивать стоит доли между группами, а не абсолютную конверсию.
    """
    scored = LeadScore.query.filter_by(model_id=record.id).all()
    graded = [s for s in scored if s.grade]
    booking = features.load_booking_dates(_engine(), lead_ids=[s.estate_buy_id for s in graded]) \
        if graded else pd.Series(dtype='datetime64[ns]')

    def booked(item):
        # Бронь считается, только если поставлена после поступления заявки.
        date = booking.get(item.estate_buy_id)
        return date is not None and not pd.isna(date) and date >= item.lead_created_at

    groups = {}
    for item in graded:
        group = groups.setdefault(item.grade, {'grade': item.grade, 'leads': 0, 'booked': 0})
        group['leads'] += 1
        group['booked'] += int(booked(item))
    total_leads = sum(g['leads'] for g in groups.values())
    total_booked = sum(g['booked'] for g in groups.values())
    for group in groups.values():
        group['leads_share'] = round(group['leads'] * 100 / total_leads, 1) if total_leads else None
        group['booking_rate'] = round(group['booked'] * 100 / group['leads'], 2) if group['leads'] else None
        group['bookings_share'] = round(group['booked'] * 100 / total_booked, 1) if total_booked else None

    skipped = {}
    for item in scored:
        if item.skip_reason:
            skipped[item.skip_reason] = skipped.get(item.skip_reason, 0) + 1

    recent = sorted(graded, key=lambda s: s.lead_created_at or datetime.min, reverse=True)[:recent_limit]
    dates = [s.lead_created_at for s in scored if s.lead_created_at]
    return {
        'groups': [groups[g] for g, _ in GRADE_SHARES if g in groups],
        'total_leads': total_leads,
        'total_booked': total_booked,
        'skipped': sorted(skipped.items(), key=lambda kv: -kv[1]),
        'period': (min(dates), max(dates)) if dates else None,
        'recent': [{'lead_id': s.estate_buy_id, 'created_at': s.lead_created_at, 'grade': s.grade,
                    'score': s.score, 'channel_type': s.channel_type, 'utm_source': s.utm_source,
                    'booked': booked(s)} for s in recent],
    }

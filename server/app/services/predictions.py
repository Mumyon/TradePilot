from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..ml.pipeline import BAR, KST, LABELS, Bar, feature_rows, label, load_artifact, predict, scale
from ..models import Candle, PredictionRecord, new_id, now

REASONS = {
    "model_not_configured": "모델 학습 대기: 과거 OHLCV CSV로 학습한 모델을 연결하세요.",
    "model_invalid": "모델 파일을 읽거나 검증할 수 없습니다.",
    "synthetic_model": "합성 데이터 학습 모델은 실제 예측으로 제공하지 않습니다.",
    "quality_gate": "시험 구간에서 기준모델 대비 성능 조건을 통과하지 못했습니다.",
    "symbol_mismatch": "이 종목으로 학습한 모델이 아닙니다.",
    "insufficient_bars": "연속된 완성 5분봉이 부족합니다 (최소 35개).",
    "stale_data": "최신 완성 5분봉이 지연되었습니다.",
    "market_close": "장 마감까지 1시간이 남지 않았거나 정규장 시간이 아닙니다.",
    "training_overlap": "모델 평가 데이터 이후의 새로운 시세가 필요합니다.",
}


def unavailable(reason):
    return dict(status="unavailable", reason=reason, message=REASONS[reason])


def get_prediction(db, symbol, settings):
    if not settings.prediction_model_path:
        return unavailable("model_not_configured")
    try:
        artifact = load_artifact(Path(settings.prediction_model_path))
        if artifact["data_kind"] != "historical":
            return unavailable("synthetic_model")
        if not artifact["quality_gate_passed"]:
            return unavailable("quality_gate")
        if artifact["symbol"] != symbol:
            return unavailable("symbol_mismatch")
        return infer(db, symbol, artifact)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return unavailable("model_invalid")


def infer(db, symbol, artifact):
    """Internal deterministic inference; public entrypoint also checks artifact provenance."""
    at = now()
    rows = list(
        reversed(
            db.scalars(
                select(Candle)
                .where(
                    Candle.symbol == symbol,
                    Candle.interval == "5m",
                    Candle.source == artifact["source"],
                    Candle.complete.is_(True),
                    Candle.opened_at <= at - BAR,
                )
                .order_by(Candle.opened_at.desc())
                .limit(100)
            ).all()
        )
    )
    bars = [
        Bar(c.opened_at, c.open_won, c.high_won, c.low_won, c.close_won, c.volume) for c in rows
    ]
    features = feature_rows(bars)
    if not features or features[-1]["as_of"] != bars[-1].as_of:
        return unavailable("insufficient_bars")
    row = features[-1]
    stamp = row["as_of"]
    if not 0 <= (at - stamp).total_seconds() <= 360:
        return unavailable("stale_data")
    local = at.astimezone(KST)
    end = local.replace(hour=15, minute=30, second=0, microsecond=0)
    if (
        local.weekday() > 4
        or local.hour < 9
        or end - local < timedelta(hours=1)
        or stamp + timedelta(hours=1) > end
    ):
        return unavailable("market_close")
    from datetime import datetime

    if datetime.fromisoformat(artifact["data_end"]) >= stamp:
        return unavailable("training_overlap")
    previous = db.scalar(
        select(PredictionRecord).where(
            PredictionRecord.symbol == symbol,
            PredictionRecord.as_of == stamp,
            PredictionRecord.model_version == artifact["version"],
        )
    )
    if previous is not None:
        return previous.data
    probabilities = predict(artifact["model"], row)
    chosen = max(range(3), key=lambda k: probabilities[k])
    direction = LABELS[chosen] if probabilities[chosen] >= 0.65 else "abstain"
    scaled = scale(row["x"], artifact["model"]["center"], artifact["model"]["spread"])
    weights = artifact["model"]["weights"][chosen][1:]
    contributions = sorted(
        [
            dict(feature=name, contribution=v * w)
            for name, v, w in zip(artifact["features"], scaled, weights, strict=True)
        ],
        key=lambda x: abs(x["contribution"]),
        reverse=True,
    )[:3]
    ident = new_id()
    data = dict(
        status="available",
        prediction_id=ident,
        symbol=symbol,
        source=artifact["source"],
        up=probabilities[0],
        neutral=probabilities[1],
        down=probabilities[2],
        direction=direction,
        generated_at=at.isoformat(),
        as_of=stamp.isoformat(),
        target_at=(stamp + timedelta(hours=1)).isoformat(),
        valid_until=(stamp + timedelta(seconds=360)).isoformat(),
        model_version=artifact["version"],
        indicators=row["indicators"],
        model_factors=contributions,
        explanation=(
            "지표 값과 선형 모델 로그잇 기여를 구분합니다. 인과관계나 수익 보장이 아닙니다."
        ),
        evaluation=artifact["evaluation"],
        direction_threshold=0.65,
    )
    db.execute(
        insert(PredictionRecord)
        .values(
            id=ident,
            symbol=symbol,
            source=artifact["source"],
            as_of=stamp,
            target_at=stamp + timedelta(hours=1),
            model_version=artifact["version"],
            base_price_won=row["price"],
            data=data,
        )
        .on_conflict_do_nothing(constraint="uq_prediction_bar_model")
    )
    return db.scalar(
        select(PredictionRecord).where(
            PredictionRecord.symbol == symbol,
            PredictionRecord.as_of == stamp,
            PredictionRecord.model_version == artifact["version"],
        )
    ).data


def resolve_outcomes(db):
    pending = db.scalars(
        select(PredictionRecord)
        .where(PredictionRecord.target_at <= now(), PredictionRecord.outcome.is_(None))
        .order_by(PredictionRecord.target_at)
        .limit(500)
    ).all()
    for record in pending:
        candle = db.get(Candle, (record.symbol, "5m", record.target_at - BAR, record.source))
        if candle is None or not candle.complete:
            continue
        actual = LABELS[label(record.base_price_won, candle.close_won)]
        direction = record.data["direction"]
        record.outcome = dict(
            status="resolved",
            actual_direction=actual,
            return_percent=str(
                (candle.close_won - record.base_price_won) * 100 / record.base_price_won
            ),
            target_price_won=str(candle.close_won),
            target_at=record.target_at.isoformat(),
            correct=None if direction == "abstain" else direction == actual,
        )

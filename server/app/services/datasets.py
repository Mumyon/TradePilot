"""Private CSV datasets for research; never mutate the shared market feed."""

import csv
import hashlib
import io
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import defer

from ..ml.pipeline import Bar, validate_bars
from ..models import Dataset, Symbol, now
from .orders import lock_user

FIELDS = ["opened_at", "open_won", "high_won", "low_won", "close_won", "volume"]


def parse(body):
    raw = body.csv_text.removeprefix("\ufeff")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeError:
        raise HTTPException(422, "UTF-8 CSV를 사용하세요.") from None
    if len(encoded) > 3_000_000:
        raise HTTPException(422, "CSV는 UTF-8 기준 3MB 이하여야 합니다.")
    reader = csv.DictReader(io.StringIO(raw), strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error:
        raise HTTPException(422, "CSV 헤더 형식을 확인하세요.") from None
    if headers is None or len(headers) != 6 or set(headers) != set(FIELDS):
        raise HTTPException(422, "CSV 헤더: " + ",".join(FIELDS))
    rows, previous, contiguous, longest, gaps = [], None, 0, 0, 0
    try:
        for i, row in enumerate(reader, 2):
            if len(rows) >= 20000:
                raise HTTPException(422, "최대 20,000행까지 등록할 수 있습니다.")
            try:
                if None in row or any(row.get(k) is None for k in FIELDS):
                    raise ValueError()
                stamp = datetime.fromisoformat(row["opened_at"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError()
                values = [int(row[k]) for k in FIELDS[1:]]
                if any(abs(v) > 10**12 for v in values):
                    raise ValueError()
                bar = Bar(stamp.astimezone(UTC), *values)
                validate_bars([bar])
                if bar.as_of > now() or (previous is not None and bar.opened_at <= previous):
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                raise HTTPException(
                    422, f"{i}행: OHLCV·시간대·오름차순·완료된 평일 정규장 5분봉을 확인하세요."
                ) from None
            if previous is not None and bar.opened_at - previous != timedelta(minutes=5):
                gaps += 1
                contiguous = 0
            contiguous += 1
            longest = max(longest, contiguous)
            previous = bar.opened_at
            rows.append(dict(zip(FIELDS, [bar.opened_at.isoformat(), *values])))
    except csv.Error:
        raise HTTPException(
            422, f"{reader.line_num}행 부근 CSV 구분/따옴표 형식을 확인하세요."
        ) from None
    if not rows:
        raise HTTPException(422, "CSV에 데이터 행이 없습니다.")
    summary = dict(
        bar_count=len(rows),
        first_bar=rows[0]["opened_at"],
        last_bar=rows[-1]["opened_at"],
        longest_contiguous=longest,
        gap_count=gaps,
        sha256=hashlib.sha256(body.csv_text.encode()).hexdigest(),
        warning=(
            "출처와 휴장일·수정주가 여부는 검증하지 않습니다. "
            "구간 단절(익일 포함)은 지표를 초기화합니다."
        ),
    )
    return rows, summary


def serialize(item):
    return dict(
        id=item.id,
        name=item.name,
        symbol=item.symbol,
        provider=item.provider,
        data_kind=item.data_kind,
        created_at=item.created_at,
        **item.summary,
    )


def save(db, user_id, body):
    rows, summary = parse(body)
    lock_user(db, user_id)
    if db.get(Symbol, body.symbol) is None:
        raise HTTPException(422, "등록된 종목 코드를 선택하세요.")
    entries = db.scalars(
        select(Dataset).options(defer(Dataset.rows)).where(Dataset.user_id == user_id)
    ).all()
    for item in entries:
        if (item.symbol, item.provider, item.data_kind, item.summary["sha256"]) == (
            body.symbol,
            body.provider,
            body.data_kind,
            summary["sha256"],
        ):
            return dict(**serialize(item), reused=True)
    if len(entries) >= 50:
        raise HTTPException(409, "사용자당 최대 50개입니다. 사용하지 않는 데이터를 삭제하세요.")
    item = Dataset(
        user_id=user_id,
        name=body.name,
        symbol=body.symbol,
        provider=body.provider,
        data_kind=body.data_kind,
        rows=rows,
        summary=summary,
    )
    db.add(item)
    db.flush()
    return dict(**serialize(item), reused=False)


def owned(db, user_id, dataset_id):
    item = db.get(Dataset, dataset_id)
    if item is None or item.user_id != user_id:
        raise HTTPException(404, "데이터를 찾을 수 없습니다.")
    return item

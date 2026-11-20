"""Read-only market snapshots and the Bank of Korea's published policy rate."""

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Lock
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

MARKETS = (
    ("kospi", "코스피", "^KS11", "pt"),
    ("kosdaq", "코스닥", "^KQ11", "pt"),
    ("nasdaq", "나스닥 종합", "^IXIC", "pt"),
    ("sp500", "S&P 500", "^GSPC", "pt"),
    ("treasury", "미국 10년 국채 금리", "^TNX", "%"),
    ("oil", "WTI 원유 선물", "CL=F", "USD"),
    ("usdkrw", "달러/원", "KRW=X", "KRW"),
    ("vix", "VIX", "^VIX", "pt"),
)
BOK_URL = "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSecd=00001&menuNo=200643"
_RATE_ROW = re.compile(
    r"<td\b[^>]*>\s*(\d{4})\s*</td>\s*<td\b[^>]*>\s*(\d{1,2})월\s*(\d{1,2})일"
    r"\s*</td>\s*<td\b[^>]*>\s*(\d+(?:\.\d+)?)\s*</td>"
)
_lock = Lock()
_cache = {}
_last_attempt = None
_rate_attempt = None


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _market(client, instrument):
    code, label, symbol, unit = instrument
    response = client.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
        params={"range": "5d", "interval": "1d"},
    )
    response.raise_for_status()
    series = response.json()["chart"]["result"][0]
    meta = series["meta"]
    price = _number(meta["regularMarketPrice"])
    stamp = datetime.fromtimestamp(meta["regularMarketTime"], UTC)
    if price is None or stamp > datetime.now(UTC):
        raise ValueError("Invalid market observation")
    zone = ZoneInfo(meta["exchangeTimezoneName"])
    observed_day = stamp.astimezone(zone).date()
    closes = series["indicators"]["quote"][0]["close"]
    previous = next(
        (
            close
            for timestamp, value in reversed(list(zip(series["timestamp"], closes, strict=True)))
            if datetime.fromtimestamp(timestamp, zone).date() < observed_day
            and (close := _number(value)) not in (None, 0)
        ),
        None,
    )
    delay = _number(meta.get("exchangeDataDelayedBy"))
    return dict(
        id=code,
        label=label,
        value=price,
        unit=unit,
        as_of=stamp.isoformat(),
        change=None
        if previous is None
        else round(price - previous if unit == "%" else (price / previous - 1) * 100, 3),
        change_unit="%p" if unit == "%" else "%",
        delay_minutes=delay,
        source="Yahoo Finance",
        kind="quote",
    )


def _policy_rate(client):
    response = client.get(BOK_URL)
    response.raise_for_status()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    history = [
        (date(int(year), int(month), int(day)), float(rate))
        for year, month, day, rate in _RATE_ROW.findall(response.text)
    ]
    effective, value = max(row for row in history if row[0] <= today)
    return dict(
        id="bok_rate",
        label="한국 기준금리",
        value=value,
        unit="%",
        as_of=effective.isoformat(),
        source="한국은행",
        kind="policy",
    )


def _fetch(client, instrument):
    try:
        return _policy_rate(client) if instrument is None else _market(client, instrument)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, OverflowError, OSError):
        return None


def latest():
    global _last_attempt, _rate_attempt
    with _lock:
        started = time.monotonic()
        if _last_attempt is None or started - _last_attempt >= 45:
            _last_attempt = started
            jobs = list(MARKETS)
            rate_interval = 900 if "bok_rate" in _cache else 45
            if _rate_attempt is None or started - _rate_attempt >= rate_interval:
                jobs.append(None)
                _rate_attempt = started
            with (
                httpx.Client(timeout=5, headers={"User-Agent": "Mozilla/5.0"}) as client,
                ThreadPoolExecutor(max_workers=len(jobs)) as pool,
            ):
                for item in pool.map(lambda job: _fetch(client, job), jobs):
                    if item is None:
                        continue
                    previous = _cache.get(item["id"])
                    if previous is None or item["as_of"] >= previous["as_of"]:
                        _cache[item["id"]] = item
        return {"items": list(_cache.values())}

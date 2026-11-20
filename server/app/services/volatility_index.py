"""Latest published daily Cboe VIX close."""

import csv
import math
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VIX_URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
_lock = Lock()
_last_attempt = None
_cached = None


def parse_closes(payload, today):
    closes = {}
    for row in csv.DictReader(payload.splitlines()):
        try:
            day = datetime.strptime(row["DATE"], "%m/%d/%Y").date()
            close = float(row["CLOSE"])
        except (KeyError, TypeError, ValueError):
            continue
        if day <= today and math.isfinite(close) and close > 0:
            closes[day] = close
    days = sorted(closes)
    if not days:
        raise ValueError("No VIX closes")
    latest = days[-1]
    return {
        "as_of": latest.isoformat(),
        "close": closes[latest],
        "change": round(closes[latest] - closes[days[-2]], 2) if len(days) >= 2 else None,
    }


def latest():
    global _last_attempt, _cached
    at = datetime.now(UTC)
    today = at.astimezone(ZoneInfo("America/New_York")).date()
    with _lock:
        if _last_attempt is None or at >= _last_attempt + timedelta(minutes=15):
            _last_attempt = at
            try:
                request = Request(VIX_URL, headers={"Accept": "text/csv"})
                with urlopen(request, timeout=5) as response:
                    parsed = parse_closes(response.read(2_000_000).decode("utf-8-sig"), today)
                if _cached is None or parsed["as_of"] >= _cached["as_of"]:
                    _cached = parsed
            except (OSError, URLError, ValueError):
                pass
        cached = _cached
    return {
        "status": "available" if cached else "unavailable",
        "source": "Cboe",
        "interval": "1d",
        **(cached or {}),
        "stale": cached is None or today - date.fromisoformat(cached["as_of"]) > timedelta(days=4),
    }

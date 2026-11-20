"""Toss Securities read-only market data adapter.

Toss REST responses are normalized here. Order execution remains the TradePilot
paper simulator; this adapter deliberately contains no account/order methods.
"""

import asyncio
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..services.candles import aggregate_chart_candles
from .contracts import MarketQuote
from .stream import StreamingMarketData

BASE_URL = "https://openapi.tossinvest.com"
SOURCE = "toss_kr"
logger = logging.getLogger(__name__)


class TossUnavailable(RuntimeError):
    """Sanitized provider error. Never keep response bodies or credentials."""


def _request(method, path, *, token=None, form=None, query=None):
    url = BASE_URL + path
    if query:
        url += "?" + urlencode(query)
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form).encode()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(4_000_000))
            if not isinstance(payload, dict):
                raise ValueError
            return payload
    except HTTPError as exc:
        # Error body and URLs can contain sensitive data; only status survives.
        raise TossUnavailable(f"토스 Open API 오류 (HTTP {exc.code})") from None
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise TossUnavailable("토스 Open API 통신 오류: " + type(exc).__name__) from None


def _rows(payload, *keys):
    value = payload.get("result", payload)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            rows = value.get(key)
            if isinstance(rows, list):
                return rows
    raise TossUnavailable("토스 API 응답 형식을 확인하지 못했습니다.")


def _first(row, *keys, default=None):
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return default


def _number(value, default=0):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def complete_five_minute_candles(rows):
    groups = {}
    for row in rows:
        start = int(row["opened_at"].timestamp()) // 300 * 300
        groups.setdefault(start, {})[row["opened_at"]] = row
    complete = []
    for start, grouped in sorted(groups.items()):
        stamps = sorted(grouped)
        expected = [datetime.fromtimestamp(start + i * 60, UTC) for i in range(5)]
        if stamps != expected:
            continue
        bars = [grouped[t] for t in stamps]
        complete.append(
            dict(
                opened_at=expected[0],
                open_won=bars[0]["open_won"],
                high_won=max(b["high_won"] for b in bars),
                low_won=min(b["low_won"] for b in bars),
                close_won=bars[-1]["close_won"],
                volume=sum(b["volume"] for b in bars),
                source=SOURCE,
                complete=True,
            )
        )
    return complete


class TossMarketData(StreamingMarketData):
    """Fetch market-wide rankings and prices, cache quotes for paper trading."""

    def __init__(self, settings):
        # The stream container is reused for its thread-safe quote/candle cache;
        # upstream Toss market data currently uses REST polling.
        super().__init__([], SOURCE)
        self.settings = settings
        self._token = None
        self._token_expires = 0.0
        self._auth_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._snapshot = None
        self._snapshot_at = 0.0
        self._rank_rows = []
        self._discovery_candles = {}
        self._previous_closes = {}
        self._execution_quotes = {}
        self._priority_symbols = []
        self._order_symbols = []
        self._chart_subscriptions = {}
        self._calendar_retry_at = 0.0
        self._feedback_candles = {}
        self._feedback_checked = {}
        self._feedback_refresh_lock = threading.Lock()
        self._chart_history = {}
        self._chart_raw = {}
        self._chart_backfills = set()
        self._chart_retry_at = {}
        self.last_error = None

    @property
    def configured(self):
        client_id = self.settings.toss_client_id
        client_secret = self.settings.toss_client_secret
        return bool(
            client_id
            and client_secret
            and client_id.get_secret_value().strip()
            and client_secret.get_secret_value().strip()
        )

    def access_token(self):
        if not self.configured:
            raise TossUnavailable("토스 Open API Client ID·Secret 설정이 필요합니다.")
        with self._auth_lock:
            if self._token and self._token_expires > time.time() + 60:
                return self._token
            result = _request(
                "POST",
                "/oauth2/token",
                form={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.toss_client_id.get_secret_value(),
                    "client_secret": self.settings.toss_client_secret.get_secret_value(),
                },
            )
            token = result.get("access_token")
            lifetime = result.get("expires_in")
            if not isinstance(token, str) or not token:
                raise TossUnavailable(
                    "토스 Open API 인증에 실패했습니다. 키와 허용 IP를 확인하세요."
                )
            try:
                lifetime = int(lifetime)
            except (TypeError, ValueError):
                lifetime = 3600
            self._token = token
            self._token_expires = time.time() + max(60, lifetime)
            return token

    def _api(self, path, query=None):
        token = self.access_token()
        try:
            return _request("GET", path, token=token, query=query)
        except TossUnavailable as exc:
            if "HTTP 401" not in str(exc):
                raise
            with self._auth_lock:
                self._token = None
                self._token_expires = 0
            return _request("GET", path, token=self.access_token(), query=query)

    def chart_details(self, symbol, section):
        if section == "orderbook":
            book = self._api("/api/v1/orderbook", {"symbol": symbol}).get("result")
            if not isinstance(book, dict):
                raise TossUnavailable("호가 응답 형식을 확인하지 못했습니다.")
            return {
                "status": "available",
                "source": "toss_kr",
                "as_of": book.get("timestamp"),
                "currency": book.get("currency"),
                "asks": book.get("asks", [])[:10],
                "bids": book.get("bids", [])[:10],
            }
        if section == "trades":
            rows = _rows(
                self._api("/api/v1/trades", {"symbol": symbol, "count": 25}), "items", "trades"
            )
            return {"status": "available", "source": "toss_kr", "items": rows[:25]}
        rows = _rows(self._api("/api/v1/stocks", {"symbols": symbol}), "items", "stocks")
        company = next((row for row in rows if row.get("symbol") == symbol), None)
        return {
            "status": "available" if company else "empty",
            "company": {
                key: company.get(key)
                for key in (
                    "name",
                    "englishName",
                    "market",
                    "securityType",
                    "currency",
                    "listDate",
                    "sharesOutstanding",
                    "isinCode",
                )
            }
            if company
            else None,
        }

    def lab_quotes(self, symbols):
        return [
            {key: row.get(key) for key in ("symbol", "lastPrice", "timestamp", "currency")}
            for row in _rows(self._api("/api/v1/prices", {"symbols": ",".join(symbols)}), "items")
            if isinstance(row, dict) and row.get("symbol") in symbols
        ]

    def lab_market_context(self, symbol, market):
        calls = {
            "calendar": (f"/api/v1/market-calendar/{market}", None),
        }
        if market == "KR":
            calls["limits"] = ("/api/v1/price-limits", {"symbol": symbol})
        else:
            calls["fx"] = ("/api/v1/exchange-rate", {"baseCurrency": "USD", "quoteCurrency": "KRW"})
        result = {}
        for name, (path, query) in calls.items():
            try:
                data = self._api(path, query).get("result")
                result[name] = data if isinstance(data, dict) else None
            except TossUnavailable:
                result[name] = None
        return result

    def _fetch_rankings(self):
        payload = self._api(
            "/api/v1/rankings",
            {
                "type": "MARKET_TRADING_AMOUNT",
                "marketCountry": "KR",
                "duration": "realtime",
                "count": self.settings.toss_ranking_count,
            },
        )
        rows = _rows(payload, "items", "rankings", "ranking", "stocks")
        normalized = []
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            nested = row.get("stock") or row.get("instrument") or {}
            if isinstance(nested, dict):
                row = {**nested, **row}
            price_info = row.get("price")
            if not isinstance(price_info, dict):
                price_info = {}
            symbol = str(_first(row, "symbol", "stockCode", "code", default=""))
            name = str(_first(row, "name", "stockName", "companyName", default=symbol))
            if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
                continue
            last_price = _number(
                _first(
                    row,
                    "lastPrice",
                    "currentPrice",
                    default=_first(price_info, "lastPrice", "price"),
                )
            )
            base_price = _number(_first(price_info, "basePrice", "previousClose"))
            percent_change = _first(
                row,
                "changePercent",
                "fluctuationRate",
                "changeRatePercent",
                default=_first(
                    price_info,
                    "changePercent",
                    "fluctuationRate",
                    "changeRatePercent",
                ),
            )
            if percent_change is None and base_price > 0 and last_price > 0:
                percent_change = (last_price - base_price) / base_price * 100
            elif percent_change is None:
                percent_change = (
                    _number(_first(row, "changeRate", default=_first(price_info, "changeRate")))
                    * 100
                )
            normalized.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "rank": int(_number(_first(row, "rank", "ranking", default=rank), rank)),
                    "price_won": int(
                        _number(
                            _first(
                                row,
                                "lastPrice",
                                "currentPrice",
                                default=_first(price_info, "lastPrice", "price"),
                            )
                        )
                    ),
                    "change_percent": percent_change,
                    "previous_close_won": int(base_price) if base_price > 0 else None,
                    "turnover_won": int(
                        _number(_first(row, "tradingAmount", "tradingValue", "turnover", "amount"))
                    ),
                    "volume": int(_number(_first(row, "tradingVolume", "volume"))),
                    "last_trade_at": None,
                    "quote_live": False,
                }
            )
        if not normalized:
            raise TossUnavailable("토스 거래대금 랭킹에 표시할 국내 종목이 없습니다.")

        # Ranking rows can omit display names; hydrate the requested symbols from
        # Toss's stock master instead of rendering numeric codes as company names.
        stock_payload = self._api(
            "/api/v1/stocks",
            {"symbols": ",".join(item["symbol"] for item in normalized)},
        )
        stock_rows = _rows(stock_payload, "items", "stocks")
        for stock in stock_rows:
            if not isinstance(stock, dict):
                continue
            symbol = str(_first(stock, "symbol", "stockCode", "code", default=""))
            name = _first(
                stock,
                "name",
                "stockName",
                "companyName",
                "koreanName",
                "displayName",
            )
            if name:
                for item in normalized:
                    if item["symbol"] == symbol:
                        item["name"] = str(name).strip()
                        break
        return normalized

    def discovery_snapshot(self, *, force=False):
        with self._snapshot_lock:
            if not force and self._snapshot and time.monotonic() - self._snapshot_at < 10:
                return self._snapshot_with_candles()
            items = self._fetch_rankings()
            symbols = [item["symbol"] for item in items]
            checked_at = datetime.now(UTC)
            with self.lock:
                watched = list(self._priority_symbols)
            requested = list(dict.fromkeys(symbols + watched))
            prices = {}
            for offset in range(0, len(requested), 200):
                payload = self._api(
                    "/api/v1/prices", {"symbols": ",".join(requested[offset : offset + 200])}
                )
                for row in _rows(payload, "prices", "items"):
                    if not isinstance(row, dict) or row.get("symbol") not in requested:
                        continue
                    price = int(_number(_first(row, "lastPrice", "price", "currentPrice")))
                    value = _first(row, "timestamp", "asOf", "updatedAt")
                    if price <= 0 or not isinstance(value, str):
                        continue
                    try:
                        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    stamp = stamp.replace(tzinfo=stamp.tzinfo or UTC).astimezone(UTC)
                    if stamp <= checked_at + timedelta(seconds=2):
                        prices[row["symbol"]] = MarketQuote(
                            row["symbol"], price, stamp, SOURCE, executable=False
                        )
            with self.lock:
                for symbol, quote in prices.items():
                    previous = self.quotes.get(symbol)
                    if previous is None or quote.as_of >= previous.as_of:
                        self.quotes[symbol] = quote
            for item in items:
                if quote := prices.get(item["symbol"]):
                    item["price_won"] = quote.price_won
                    item["last_trade_at"] = quote.as_of
                    item["quote_live"] = checked_at - quote.as_of <= timedelta(seconds=30)
            self._rank_rows = items
            self.symbols = symbols
            self._snapshot = {
                "provider": SOURCE,
                "scope": "market_wide_toss_ranking",
                "ranking_basis": "MARKET_TRADING_AMOUNT · market-wide · KR",
                "symbols": symbols,
                "checked_at": checked_at,
                "items": items,
            }
            self._snapshot_at = time.monotonic()
            return self._snapshot_with_candles()

    def _snapshot_with_candles(self):
        return {
            **self._snapshot,
            "items": [
                dict(item, candle=self._discovery_candles.get(item["symbol"]))
                for item in self._snapshot["items"]
            ],
        }

    async def _refresh_discovery_candles(self):
        # Keep per-symbol requests off the ranking response and the trade socket.
        while True:
            symbols = await asyncio.to_thread(self._discovery_symbols)
            if not symbols:
                await asyncio.sleep(1)
                continue
            for symbol in symbols:
                try:
                    rows = await asyncio.to_thread(self.get_candles, symbol, "1d", count=1)
                except TossUnavailable as exc:
                    if "HTTP 404" not in str(exc):
                        break
                else:
                    if rows:
                        await asyncio.to_thread(self._cache_discovery_candle, symbol, rows[-1])
                await asyncio.sleep(0.2)
            await asyncio.sleep(60)

    def _discovery_symbols(self):
        with self._snapshot_lock:
            symbols = list(self.symbols)
            self._discovery_candles = {
                symbol: self._discovery_candles[symbol]
                for symbol in symbols
                if symbol in self._discovery_candles
            }
            return symbols

    def _cache_discovery_candle(self, symbol, candle):
        with self._snapshot_lock:
            self._discovery_candles[symbol] = candle

    async def _refresh_rankings(self):
        while True:
            try:
                await asyncio.to_thread(self.discovery_snapshot, force=True)
            except TossUnavailable:
                pass
            await asyncio.sleep(60)

    def get_quote(self, symbol):
        with self.lock:
            return self.quotes.get(symbol)

    def get_execution_quote(self, symbol):
        with self.lock:
            return self._execution_quotes.get(symbol)

    def set_priority_symbols(self, symbols, *, orders=()):
        with self.lock:
            self._priority_symbols = list(dict.fromkeys(symbols))
            self._order_symbols = list(dict.fromkeys(orders))

    def subscription_symbols(self):
        with self.lock:
            chart = [symbol for symbol, _ in self._chart_subscriptions.values()]
            return list(
                dict.fromkeys(
                    self._order_symbols + chart + self._priority_symbols + list(self.symbols)
                )
            )[:100]

    def set_chart_subscription(self, queue, symbol=None, name=None):
        # The WebSocket handlers and the upstream receiver share the asyncio loop.
        with self.lock:
            self._chart_subscriptions.pop(queue, None)
            if symbol is not None:
                self._chart_subscriptions[queue] = (symbol, name)
            latest = self._execution_quotes.get(symbol)
        if not queue.empty():
            queue.get_nowait()
        if latest:
            queue.put_nowait((latest, name))

    def accept_trade(self, quote):
        with self.lock:
            execution = self._execution_quotes.get(quote.symbol)
            if execution and quote.as_of < execution.as_of:
                return
            self._execution_quotes[quote.symbol] = quote
            previous = self.quotes.get(quote.symbol)
            if previous is None or quote.as_of >= previous.as_of:
                self.quotes[quote.symbol] = quote
            recipients = [
                (queue, name)
                for queue, (symbol, name) in self._chart_subscriptions.items()
                if symbol == quote.symbol
            ]
        for queue, name in recipients:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait((quote, name))

    def get_market_calendar(self):
        if time.monotonic() < self._calendar_retry_at:
            raise TossUnavailable("거래일 캘린더 재조회 대기 중입니다.")
        self._calendar_retry_at = time.monotonic() + 60
        payload = self._api("/api/v1/market-calendar/KR").get("result")
        if not isinstance(payload, dict) or not isinstance(payload.get("today"), dict):
            raise TossUnavailable("토스 거래일 캘린더 응답을 확인하지 못했습니다.")
        return payload

    def get_previous_close(self, symbol):
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        with self._snapshot_lock:
            checked = self._snapshot.get("checked_at") if self._snapshot else None
            if checked and checked.astimezone(ZoneInfo("Asia/Seoul")).date() == today:
                for item in self._rank_rows:
                    if item["symbol"] == symbol and item.get("previous_close_won"):
                        return item["previous_close_won"]
            cached = self._previous_closes.get(symbol)
            if cached and cached[0] == today:
                return cached[1]
        rows = self.get_candles(symbol, "1d")
        completed = [
            row
            for row in rows
            if row["opened_at"].astimezone(ZoneInfo("Asia/Seoul")).date() < today
        ]
        if not completed:
            return None
        close = completed[-1]["close_won"]
        with self._snapshot_lock:
            self._previous_closes[symbol] = (today, close)
        return close

    def get_candles(self, symbol, interval, *, count=200, before=None):
        if interval not in ("1m", "1d", "5m", "15m", "1h"):
            return []
        source_interval = "1d" if interval == "1d" else "1m"
        query = {"symbol": symbol, "interval": source_interval, "count": count, "adjusted": "true"}
        if before is not None:
            query["before"] = before.isoformat()
        payload = self._api("/api/v1/candles", query)
        result = payload.get("result", {})
        rows = result.get("candles") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise TossUnavailable("토스 분봉 응답 형식을 확인하지 못했습니다.")
        candles = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                stamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError
                candles.append(
                    {
                        "opened_at": stamp.astimezone(UTC),
                        "open_won": int(row["openPrice"]),
                        "high_won": int(row["highPrice"]),
                        "low_won": int(row["lowPrice"]),
                        "close_won": int(row["closePrice"]),
                        "volume": int(row["volume"]),
                        "complete": True,
                        "source": SOURCE,
                    }
                )
            except (ValueError, KeyError, TypeError):
                continue
        candles.sort(key=lambda row: row["opened_at"])
        if source_interval == "1m" and before is None:
            with self.lock:
                previous = self._feedback_candles.get(symbol)
                if candles and (
                    not previous or candles[-1]["opened_at"] >= previous[-1]["opened_at"]
                ):
                    self._feedback_candles[symbol] = list(candles)
                self._feedback_checked[symbol] = time.monotonic()
        if interval in ("5m", "15m", "1h"):
            seconds = {"5m": 300, "15m": 900, "1h": 3600}[interval]
            grouped = {}
            for row in candles:
                epoch = int(row["opened_at"].timestamp())
                start = datetime.fromtimestamp(epoch // seconds * seconds, UTC)
                bar = grouped.get(start)
                if bar is None:
                    grouped[start] = dict(row, opened_at=start)
                else:
                    bar["high_won"] = max(bar["high_won"], row["high_won"])
                    bar["low_won"] = min(bar["low_won"], row["low_won"])
                    bar["close_won"] = row["close_won"]
                    bar["volume"] += row["volume"]
            candles = list(grouped.values())
        return candles

    def get_feedback_candles(self, symbol):
        # Reuse the chart's minute data. No upstream network request on order checks.
        with self.lock:
            rows = list(self._feedback_candles.get(symbol, []))
        return complete_five_minute_candles(rows)

    def _backfill_chart(self, key, newest, cutoff):
        symbol, base = key
        cursor = newest[0]["opened_at"]
        rows = list(newest)
        complete = False
        try:
            for _ in range(40):
                if cursor <= cutoff:
                    complete = True
                    break
                time.sleep(0.22)
                older = self.get_candles(symbol, base, before=cursor - timedelta(seconds=1))
                if not older or older[0]["opened_at"] >= cursor:
                    complete = True
                    break
                rows.extend(older)
                cursor = older[0]["opened_at"]
        except TossUnavailable:
            pass
        finally:
            with self.lock:
                self._chart_backfills.remove(key)
                self._chart_retry_at[key] = time.monotonic() + (900 if complete else 45)
                by_stamp = {row["opened_at"]: row for row in rows}
                stamps = sorted(by_stamp)
                start = next((i for i, stamp in enumerate(stamps) if stamp >= cutoff), len(stamps))
                self._chart_raw[key] = [by_stamp[stamp] for stamp in stamps[max(0, start - 1) :]]

    def get_chart_candles(self, symbol, interval):
        key = (symbol, interval)
        at = datetime.now(UTC)
        daily = interval in ("1d", "1w", "1mo", "1y")
        base = "1d" if daily else "1m"
        raw_key = (symbol, base)
        cutoff = at - timedelta(days=365 * 7 if daily else 7)
        with self.lock:
            cached_at, cached = self._chart_history.get(key, (None, []))
            if cached_at and at - cached_at < timedelta(seconds=5):
                return cached
        if daily:
            latest = self.get_candles(symbol, base)
        else:
            self.refresh_feedback_candles(symbol)
            with self.lock:
                latest = list(self._feedback_candles.get(symbol, []))
        with self.lock:
            history = self._chart_raw.get(raw_key, [])
            raw = {row["opened_at"]: row for row in [*history, *latest]}
            ordered = [raw[stamp] for stamp in sorted(raw)]
            if latest and (
                raw_key not in self._chart_backfills
                and len(self._chart_backfills) < 2
                and time.monotonic() >= self._chart_retry_at.get(raw_key, 0)
            ):
                if len(self._chart_raw) >= 24 and raw_key not in self._chart_raw:
                    oldest = next(
                        key for key in self._chart_raw if key not in self._chart_backfills
                    )
                    del self._chart_raw[oldest]
                    self._chart_retry_at.pop(oldest, None)
                self._chart_backfills.add(raw_key)
                threading.Thread(
                    target=self._backfill_chart, args=(raw_key, ordered, cutoff), daemon=True
                ).start()
        rows = aggregate_chart_candles(ordered, interval, at, include_current=True)
        if interval in {"1w", "1mo", "1y"} and len(rows) > 1:
            rows = rows[1:]
        if not daily:
            rows = [row for row in rows if row["closed_at"] >= cutoff]
        else:
            rows = rows[-120:]
        with self.lock:
            if len(self._chart_history) >= 128 and key not in self._chart_history:
                del self._chart_history[next(iter(self._chart_history))]
            self._chart_history[key] = (at, rows)
        return rows

    def refresh_feedback_candles(self, symbol):
        with self._feedback_refresh_lock:
            with self.lock:
                checked = self._feedback_checked.get(symbol)
                fresh = checked is not None and time.monotonic() - checked < 5
            if not fresh:
                self.get_candles(symbol, "1m")

    def status(self):
        if not self.configured:
            self.state = "waiting_credentials"
        return {
            "state": self.state,
            "message": {
                "waiting_credentials": "토스 Open API 키 설정 대기",
                "connecting": "토스 시세 조회 연결 중",
                "receiving": "토스 시세 수신 중",
                "reconnecting": "토스 시세 재조회 대기",
                "stopped": "시세 수신 중지",
            }.get(self.state, self.state),
            "provider": "토스증권 Open API",
            "source": SOURCE,
            "last_trade_at": max((q.as_of for q in self.quotes.values()), default=None),
            "symbols": self.symbols,
            "execution": "paper_only",
            "transport": "Toss WebSocket → TradePilot WebSocket; REST ranking/candles",
            "last_error": self.last_error,
        }

    async def run(self):
        if not self.configured:
            self.state = "waiting_credentials"
            return
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._refresh_discovery_candles())
            tasks.create_task(self._refresh_rankings())
            await self._run_feed()

    async def _run_feed(self):
        from websockets.asyncio.client import connect

        delay = 5
        while True:
            try:
                self.state = "connecting"
                token = await asyncio.to_thread(self.access_token)
                async with connect(
                    "wss://openapi-ws.tossinvest.com/ws/v1",
                    additional_headers={"Authorization": "Bearer " + token},
                    ping_interval=None,
                    open_timeout=12,
                    close_timeout=5,
                    max_size=1_000_000,
                ) as ws:
                    requested = self.subscription_symbols() or ["005930", "000660"]
                    await ws.send(json.dumps([{"type": "trade:kr", "codes": requested}]))
                    ack_raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    ack = json.loads(ack_raw)
                    expected = {f"trade:kr:{symbol}" for symbol in requested}
                    subscribed = set(ack.get("subscribed", [])) if isinstance(ack, dict) else set()
                    if not isinstance(ack, dict) or ack.get("type") != "subscriptions":
                        raise TossUnavailable("토스 실시간 시세 구독 응답을 확인하지 못했습니다.")
                    if not subscribed:
                        raise TossUnavailable("토스 실시간 시세 종목 구독이 거절되었습니다.")
                    if not subscribed.issubset(expected):
                        raise TossUnavailable("토스 시세 구독 종목을 확인하지 못했습니다.")
                    self.state = "subscribed"
                    self.last_error = None
                    delay = 5
                    last_ping = time.monotonic()
                    last_declaration = last_ping
                    while True:
                        if time.time() >= self._token_expires - 60:
                            raise TossUnavailable("토스 시세 연결 인증 갱신을 위해 재연결합니다.")
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        except TimeoutError:
                            raw = None
                        now = time.monotonic()
                        if now - last_ping >= 60:
                            await ws.send("PING")
                            last_ping = now
                        desired = self.subscription_symbols() or ["005930", "000660"]
                        if desired != requested and now - last_declaration >= 0.25:
                            requested = desired
                            await ws.send(json.dumps([{"type": "trade:kr", "codes": requested}]))
                            last_declaration = now
                        if raw is None:
                            continue
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        if raw == "PING":
                            await ws.send("PING")
                            continue
                        message = json.loads(raw)
                        if not isinstance(message, dict):
                            continue
                        if message.get("type") == "error":
                            raise TossUnavailable("토스 실시간 시세 연결에서 오류가 발생했습니다.")
                        if message.get("type") == "subscriptions":
                            accepted = set(message.get("subscribed") or [])
                            if not accepted:
                                raise TossUnavailable(
                                    "토스 실시간 시세 종목 재구독에 실패했습니다."
                                )
                            self.state = "subscribed"
                            continue
                        if message.get("type") == "pong":
                            continue
                        if message.get("type") != "message":
                            continue
                        topic = message.get("topic", "")
                        prefix, separator, symbol = topic.rpartition(":")
                        data = message.get("data", {})
                        if prefix != "trade:kr" or not separator or symbol not in requested:
                            continue
                        try:
                            price = int(float(data["price"]))
                            stamp = datetime.fromisoformat(
                                str(data["timestamp"]).replace("Z", "+00:00")
                            )
                            if stamp.tzinfo is None or price <= 0:
                                continue
                            stamp = stamp.astimezone(UTC)
                        except (ValueError, KeyError, TypeError):
                            continue
                        received_at = datetime.now(UTC)
                        if stamp > received_at + timedelta(
                            seconds=2
                        ) or received_at - stamp > timedelta(seconds=30):
                            continue
                        self.accept_trade(MarketQuote(symbol, price, stamp, SOURCE))
                        self.state = "receiving"
            except asyncio.CancelledError:
                self.state = "stopped"
                raise
            except Exception as exc:
                self.state = "reconnecting"
                self.last_error = (
                    str(exc) if isinstance(exc, TossUnavailable) else type(exc).__name__
                )
                logger.warning("Toss market data unavailable; retry scheduled")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

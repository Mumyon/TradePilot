"""Thread-safe cache shared by read-only stream adapters and the paper worker."""

from collections import defaultdict, deque
from datetime import UTC, datetime
from threading import RLock
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


class StreamingMarketData:
    def __init__(self, symbols, source):
        self.symbols = symbols
        self.source = source
        self.lock = RLock()
        self.quotes = {}
        self.volumes = {}
        self.active = {}
        self.bars = defaultdict(lambda: deque(maxlen=120))
        self.connected_at = None
        self.state = "waiting_credentials"

    def get_quote(self, symbol):
        with self.lock:
            return self.quotes.get(symbol)

    def get_candles(self, symbol, interval):
        with self.lock:
            return [dict(row) for row in self.bars[(symbol, interval)]]

    def status(self):
        with self.lock:
            latest = max((q.as_of for q in self.quotes.values()), default=None)
            return {
                "state": self.state,
                "message": {
                    "waiting_credentials": "API 키 설정 대기",
                    "auth_failed": "API 인증 확인 필요",
                    "connecting": "연결 중",
                    "subscribing": "종목 구독 중",
                    "subscribed": "구독 완료 · 체결 데이터 대기",
                    "receiving": "실제 체결 데이터 수신",
                    "reconnecting": "연결 끊김 · 재연결 중",
                    "stopped": "수신 중지",
                }[self.state],
                "source": self.source,
                "last_trade_at": latest,
                "symbols": self.symbols,
                "execution": "paper_only",
            }

    def reset_connection(self, at=None):
        with self.lock:
            self.connected_at = at
            self.active.clear()  # A reconnect must not certify a partially observed bar.
            self.volumes.clear()
            self.quotes.clear()  # Database retains last price with its original age.

    def accept_trades(self, trades, received_at):
        with self.lock:
            for quote, cumulative in trades:
                if quote.symbol not in self.symbols:
                    continue
                old = self.quotes.get(quote.symbol)
                if old and quote.as_of.astimezone(KST).date() != old.as_of.astimezone(KST).date():
                    self.reset_connection(received_at)
                    old = None
                if old and quote.as_of < old.as_of:
                    continue
                prior_volume = self.volumes.get(quote.symbol)
                if prior_volume is not None and cumulative <= prior_volume:
                    continue  # retransmission / reordered packet
                self.quotes[quote.symbol] = quote
                self.volumes[quote.symbol] = cumulative
                self.state = "receiving"
                for interval, seconds in INTERVALS.items():
                    start = datetime.fromtimestamp(
                        int(quote.as_of.timestamp()) // seconds * seconds, UTC
                    )
                    key = (quote.symbol, interval)
                    bar = self.active.get(key)
                    if bar and bar["opened_at"] != start:
                        self.bars[key].append(dict(bar, complete=True))
                        self.active.pop(key)
                        bar = None
                    # Exclude the first partial window and first tick after connection.
                    if (
                        self.connected_at is None
                        or start <= self.connected_at
                        or prior_volume is None
                    ):
                        continue
                    if bar is None:
                        bar = dict(
                            opened_at=start,
                            open_won=quote.price_won,
                            high_won=quote.price_won,
                            low_won=quote.price_won,
                            close_won=quote.price_won,
                            volume=0,
                            complete=False,
                            source=self.source,
                        )
                        self.active[key] = bar
                    bar["high_won"] = max(bar["high_won"], quote.price_won)
                    bar["low_won"] = min(bar["low_won"], quote.price_won)
                    bar["close_won"] = quote.price_won
                    bar["volume"] += cumulative - prior_volume

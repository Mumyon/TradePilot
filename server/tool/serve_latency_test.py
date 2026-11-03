"""Disposable integration server with changing test prices. Never a broker feed."""

from threading import Lock

import app.api as api
from app.brokers.contracts import MarketQuote
from app.brokers.demo import DemoMarketData
from app.models import now
from tool.serve_integration import main


class ChangingTestData(DemoMarketData):
    def __init__(self):
        self.count = 0
        self.lock = Lock()

    def get_quote(self, symbol):
        if symbol not in ("005930", "000660"):
            return None
        with self.lock:
            self.count += 1
            return MarketQuote(symbol, 70000 + self.count, now(), "demo")


if __name__ == "__main__":
    api.market_data_provider = lambda settings: ChangingTestData()
    main()

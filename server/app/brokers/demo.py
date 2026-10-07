from ..models import now
from .contracts import MarketQuote


class DemoMarketData:
    """Explicit synthetic prices, never a fallback for a failed real provider."""

    def get_quote(self, symbol: str) -> MarketQuote | None:
        price = {"005930": 72800, "000660": 173500}.get(symbol)
        return MarketQuote(symbol, price, now(), "demo") if price else None

    def get_candles(self, symbol: str, interval: str) -> list[dict]:
        return []

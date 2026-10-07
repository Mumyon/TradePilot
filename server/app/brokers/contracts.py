"""Broker boundary: vendor response formats must not escape this module."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class BrokerNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price_won: int
    as_of: datetime
    source: str


@dataclass(frozen=True)
class BrokerOrder:
    account_id: str
    symbol: str
    side: str
    quantity: int
    limit_price_won: int
    client_order_id: str


@dataclass(frozen=True)
class BrokerOrderResult:
    broker_order_id: str
    status: str


@dataclass(frozen=True)
class ExecutionEvent:
    event_id: str
    broker_order_id: str
    filled_quantity: int
    filled_price_won: int
    occurred_at: datetime


class MarketDataPort(Protocol):
    def get_quote(self, symbol: str) -> MarketQuote | None: ...
    def get_candles(self, symbol: str, interval: str) -> list[dict]: ...


class ExecutionPort(Protocol):
    def get_balance(self, account_id: str) -> dict: ...
    def place_order(self, order: BrokerOrder) -> BrokerOrderResult: ...
    def cancel_order(self, account_id: str, broker_order_id: str) -> BrokerOrderResult: ...
    def executions(self, account_id: str) -> Iterator[ExecutionEvent]: ...

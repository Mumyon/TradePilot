from .contracts import BrokerNotConfigured, BrokerOrder


class BrokerAdapterTemplate:
    """Replace these methods when a specific broker is selected.

    No credentials are read, no network requests or real orders are made.
    This adapter is deliberately NOT wired to the paper order service.
    """

    def _access_token(self) -> str:
        # TODO(broker-auth): credential lookup, token expiry, refresh and rate limits.
        raise BrokerNotConfigured("증권사 인증 어댑터가 연결되지 않았습니다.")

    def get_quote(self, symbol: str):
        # TODO(broker-quotes): normalize the vendor's quote to MarketQuote.
        raise BrokerNotConfigured("증권사 시세가 연결되지 않았습니다.")

    def get_candles(self, symbol: str, interval: str):
        # TODO(broker-candles): timezone-aware OHLCV, pagination, completed candles.
        raise BrokerNotConfigured("증권사 차트가 연결되지 않았습니다.")

    def get_balance(self, account_id: str):
        # TODO(broker-account): resolve the authenticated user's broker account.
        raise BrokerNotConfigured("증권사 잔고가 연결되지 않았습니다.")

    def place_order(self, order: BrokerOrder):
        # TODO(broker-orders): stable client_order_id, timeout reconciliation.
        raise BrokerNotConfigured("실계좌 주문은 활성화되지 않았습니다.")

    def cancel_order(self, account_id: str, broker_order_id: str):
        # TODO(broker-cancel): do not mark cancelled until vendor confirmation.
        raise BrokerNotConfigured("증권사 주문 취소가 연결되지 않았습니다.")

    def executions(self, account_id: str):
        # TODO(broker-executions): reconnect, replay, stable unique event IDs.
        raise BrokerNotConfigured("증권사 체결 스트림이 연결되지 않았습니다.")

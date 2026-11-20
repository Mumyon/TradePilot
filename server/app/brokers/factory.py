from ..config import Settings
from .contracts import ExecutionPort, MarketDataPort
from .demo import DemoMarketData
from .template import BrokerAdapterTemplate


def market_data_provider(settings: Settings) -> MarketDataPort:
    if settings.market_data_mode == "demo":
        return DemoMarketData()
    if settings.market_data_mode == "kis":
        from .kis import KisMarketData

        return KisMarketData(settings)
    if settings.market_data_mode == "namuh":
        from .namuh import NamuhMarketData

        return NamuhMarketData(settings)
    if settings.market_data_mode == "toss":
        from .toss import TossMarketData

        return TossMarketData(settings)
    return BrokerAdapterTemplate()


def execution_provider() -> ExecutionPort:
    # This port is not invoked by paper order acceptance.
    return BrokerAdapterTemplate()

from ..config import Settings
from .contracts import ExecutionPort, MarketDataPort
from .demo import DemoMarketData
from .template import BrokerAdapterTemplate


def market_data_provider(settings: Settings) -> MarketDataPort:
    # TODO(broker-wiring): add a named provider here after implementing contracts.
    if settings.market_data_mode == "demo":
        return DemoMarketData()
    return BrokerAdapterTemplate()


def execution_provider() -> ExecutionPort:
    # This port is not invoked by paper order acceptance.
    return BrokerAdapterTemplate()

"""Read-only KRX trade stream. No account numbers, balances or order endpoints."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .contracts import MarketQuote
from .stream import StreamingMarketData

SOURCE = "kis_krx"
KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)
socket_logger = logging.getLogger(__name__ + ".transport")
socket_logger.setLevel(logging.WARNING)
socket_logger.propagate = False
socket_logger.addHandler(logging.NullHandler())


def parse_trades(raw, received_at):
    """Use exchange business date AND time; never turn receipt time into quote time."""
    kind, transaction, count, payload = raw.split("|", 3)
    if kind != "0" or transaction != "H0STCNT0":
        raise ValueError("Unsupported stream")
    count = int(count)
    fields = payload.split("^")
    if not 1 <= count <= 100 or len(fields) % count:
        raise ValueError("Invalid record count")
    width = len(fields) // count
    if width not in (46, 47):
        raise ValueError("Unknown trade schema")
    result = []
    for offset in range(0, len(fields), width):
        row = fields[offset : offset + width]
        symbol = row[0]
        stamp = datetime.strptime(row[33] + row[1], "%Y%m%d%H%M%S").replace(tzinfo=KST)
        price, volume = int(row[2]), int(row[13])
        if (
            len(symbol) != 6
            or not symbol.isascii()
            or not symbol.isdigit()
            or price <= 0
            or volume < 0
            or stamp > received_at + timedelta(seconds=2)
            or received_at - stamp > timedelta(seconds=15)
        ):
            raise ValueError("Invalid or delayed trade")
        # Continuous KRX regular session only; no auction/after-hours simulated fills.
        if not ("090000" <= row[1] < "152000") or stamp.weekday() >= 5:
            continue
        result.append((MarketQuote(symbol, price, stamp.astimezone(UTC), SOURCE), volume))
    return result


class KisMarketData(StreamingMarketData):
    def __init__(self, settings):
        super().__init__(settings.kis_symbols, SOURCE)
        self.settings = settings

    def accept(self, raw, received_at):
        self.accept_trades(parse_trades(raw, received_at), received_at)

    def approval(self):
        body = {
            "grant_type": "client_credentials",
            "appkey": self.settings.kis_app_key.get_secret_value(),
            "secretkey": self.settings.kis_app_secret.get_secret_value(),
        }
        request = Request(
            "https://openapi.koreainvestment.com:9443/oauth2/Approval",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            key = json.load(response).get("approval_key")
        if not isinstance(key, str) or not key:
            raise ValueError("Approval unavailable")
        return key

    async def run(self):
        from websockets.asyncio.client import connect

        if not self.settings.kis_app_key or not self.settings.kis_app_secret:
            self.state = "waiting_credentials"
            return
        delay = 5
        while True:
            try:
                self.state = "connecting"
                approval = await asyncio.to_thread(self.approval)
                async with connect(
                    "ws://ops.koreainvestment.com:21000",
                    ping_interval=None,
                    logger=socket_logger,
                    open_timeout=10,
                    close_timeout=5,
                    max_size=1_000_000,
                ) as ws:
                    self.reset_connection(datetime.now(UTC))
                    self.state = "subscribing"
                    for symbol in self.settings.kis_symbols:
                        await ws.send(
                            json.dumps(
                                {
                                    "header": {
                                        "approval_key": approval,
                                        "custtype": "P",
                                        "tr_type": "1",
                                        "content-type": "utf-8",
                                    },
                                    "body": {"input": {"tr_id": "H0STCNT0", "tr_key": symbol}},
                                }
                            )
                        )
                        await asyncio.sleep(0.1)
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=90)
                        if not isinstance(raw, str):
                            raise ValueError("Invalid frame")
                        if raw.startswith("{"):
                            message = json.loads(raw)
                            if message.get("header", {}).get("tr_id") == "PINGPONG":
                                await ws.pong(raw.encode())
                            elif message.get("body", {}).get("rt_cd") != "0":
                                raise ValueError("Subscription rejected")
                            else:
                                self.state = "subscribed"
                        else:
                            self.accept(raw, datetime.now(UTC))
                            delay = 5
            except asyncio.CancelledError:
                self.reset_connection()
                self.state = "stopped"
                raise
            except Exception:
                # Never log raw responses, subscription frames, keys or exception bodies.
                self.reset_connection()
                self.state = "reconnecting"
                logger.warning("KIS market stream unavailable; reconnect scheduled")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)

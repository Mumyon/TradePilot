"""Namuh PLUG quote-only adapter; fixed endpoints deliberately exclude orders/accounts."""

import asyncio
import fcntl
import hashlib
import http.client
import json
import logging
import os
import re
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from .contracts import MarketQuote
from .stream import KST, StreamingMarketData

SOURCE = "namuh_krx"
PERIOD_PATH = "/krstock/quote/v1/period"
CURRENT_PRICE_PATH = "/krstock/quote/v1/currentPrice"
WS_URL = "wss://api.nhplug.com:7070/websocket"
logger = logging.getLogger(__name__)
socket_logger = logging.getLogger(__name__ + ".transport")
socket_logger.setLevel(logging.WARNING)
socket_logger.propagate = False
socket_logger.addHandler(logging.NullHandler())


class NamuhUnavailable(RuntimeError):
    """Sanitized errors only: never retain URL queries, response bodies or tokens."""


class NamuhAuthRejected(NamuhUnavailable):
    pass


def tls_context():
    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _post(path, *, query=None, body=None, token=None):
    if path not in ("/oauth2/token", PERIOD_PATH, CURRENT_PRICE_PATH):
        raise ValueError("Unsupported Namuh endpoint")
    headers = {"Content-Type": "application/json"}
    if path == "/oauth2/token":
        path += "?" + urlencode(query)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = "Bearer " + token
    connection = http.client.HTTPSConnection(
        "api.nhplug.com", 8443, timeout=10, context=tls_context()
    )
    try:
        connection.request("POST", path, body=json.dumps(body) if body else b"", headers=headers)
        response = connection.getresponse()
        status = response.status
        if status != 200:
            # Keep only a documented-format diagnostic code, never the error body/query.
            raw_error = response.read(200_000).decode("utf-8", errors="replace")
            match = re.search(r"\b(?:IGW|WSS)[0-9]{5}\b", raw_error)
            return status, {"error_code": match.group() if match else "unclassified"}
        data = json.loads(response.read(2_000_000))
        if not isinstance(data, dict):
            raise ValueError
        return status, data
    except Exception as exc:
        raise NamuhUnavailable(
            "나무 시세 서버 통신 또는 응답 형식 오류: " + type(exc).__name__
        ) from None
    finally:
        connection.close()


def _write_private(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".token-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class NamuhToken:
    def __init__(self, settings):
        self.settings = settings
        self.expiry = 0

    @property
    def path(self):
        key = self.settings.nhplug_app_key.get_secret_value()
        secret = self.settings.nhplug_app_secret.get_secret_value()
        scope = hashlib.sha256((key + "|" + secret).encode()).hexdigest()
        return self.settings.nhplug_token_cache_dir / (scope + ".json")

    def get(self):
        path = self.path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                cached = json.loads(path.read_text())
                self.expiry = float(cached["expires_at"])
                if (
                    self.expiry > time.time() + 60
                    and isinstance(cached["token"], str)
                    and cached["token"]
                ):
                    return cached["token"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
            status, result = _post(
                "/oauth2/token",
                query={
                    "appkey": self.settings.nhplug_app_key.get_secret_value(),
                    "appsecretkey": self.settings.nhplug_app_secret.get_secret_value(),
                    "grant_type": "client_credentials",
                    "scope": "oob",
                },
            )
            token = result.get("access_token")
            if status != 200 or not isinstance(token, str) or not token:
                error = NamuhAuthRejected if status in (400, 401, 403) else NamuhUnavailable
                code = result.get("error_code", "unclassified")
                raise error(
                    f"나무 API 인증 실패 (HTTP {status}, {code}): 키·서비스 신청 상태 확인 필요"
                )
            try:
                lifetime = int(result["expires_in"])
                if not 60 < lifetime <= 86400:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise NamuhUnavailable("나무 토큰 만료 정보 확인 실패") from None
            self.expiry = time.time() + lifetime
            _write_private(path, {"token": token, "expires_at": self.expiry})
            return token

    def invalidate(self):
        self.path.unlink(missing_ok=True)
        self.expiry = 0


@dataclass(frozen=True)
class MarketSession:
    day: date
    start: str
    auction: str


def market_session(data):
    block = data.get("Output_0")
    message = str(data.get("rsp_msg", ""))
    if (
        not isinstance(block, dict)
        or not ("정상" in message or ("조회" in message and "완료" in message))
        or any(word in message for word in ("실패", "오류", "불가", "없", "초과", "만료"))
    ):
        raise NamuhUnavailable("나무 영업일 조회 확인 실패")
    try:
        day = datetime.strptime(block["bsop_date"], "%Y%m%d").date()
        start = block["start_time"]
        auction = block["cncc_aspr_sta_hour"]
        for stamp in (start, auction):
            if not re.fullmatch(r"[0-9]{6}", stamp):
                raise ValueError
            datetime.strptime(stamp, "%H%M%S")
        if start >= auction:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise NamuhUnavailable("나무 영업일·연속매매 시간 확인 실패") from None
    return MarketSession(day, start, auction)


def parse_trade(message, sessions, received_at):
    header, body = message.get("header", {}), message.get("body", {})
    if header.get("tr_cd") != "oc" or "rsp_cd" in header or "tr_type" in header:
        raise ValueError("Not a KRX trade push")
    symbol = header.get("tr_key")
    session = sessions.get(symbol)
    if session is None or body.get("code") != symbol:
        raise ValueError("Unexpected symbol")
    # WS time has no date: use REST-confirmed business day, never receipt date alone.
    if session.day != received_at.astimezone(KST).date():
        return []
    raw_time = body.get("time", "")
    if not isinstance(raw_time, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}", raw_time):
        raise ValueError("Invalid exchange time")
    clock = raw_time.replace(":", "")
    stamp = datetime.combine(session.day, datetime.strptime(clock, "%H%M%S").time(), KST)
    if not session.start <= clock < session.auction:
        return []
    if not -2 <= (received_at - stamp).total_seconds() <= 15:
        raise ValueError("Delayed or future trade")
    values = [body.get("price"), body.get("volume")]
    if any(not re.fullmatch(r"[0-9]+", str(value)) for value in values):
        raise ValueError("Invalid price or cumulative volume")
    price, volume = map(int, values)
    if price <= 0 or price > 10**12 or volume > 10**15:
        raise ValueError("Invalid trade values")
    return [(MarketQuote(symbol, price, stamp.astimezone(UTC), SOURCE), volume)]


class NamuhMarketData(StreamingMarketData):
    def __init__(self, settings):
        super().__init__(settings.nhplug_symbols, SOURCE)
        self.settings = settings
        self.tokens = NamuhToken(settings)
        self.sessions = {}
        self.last_error = None
        self._ranking_lock = threading.Lock()
        self._ranking_cache = None
        self._ranking_cached_at = 0.0

    def discovery_snapshot(self):
        """Current turnover and volume for this adapter's registered symbols only."""
        with self._ranking_lock:
            if self._ranking_cache and time.monotonic() - self._ranking_cached_at < 10:
                return self._ranking_cache

            token = self.tokens.get()
            checked_at = datetime.now(UTC)
            items = []
            for symbol in self.symbols:
                status, result = _post(
                    CURRENT_PRICE_PATH,
                    token=token,
                    body={"Input_0": {"market_cd": "KRX", "iem_cd": symbol}},
                )
                if status == 401:
                    self.tokens.invalidate()
                if status != 200:
                    raise NamuhUnavailable(f"나무 종목 시세 조회 실패 (HTTP {status})")
                row = result.get("Output_0")
                if not isinstance(row, dict) or row.get("iem_cd") != symbol:
                    raise NamuhUnavailable("나무 종목 시세 응답 확인 실패")
                try:
                    price = int(row["stck_prpr"])
                    # PLUG currentPrice returns this aggregate in million-won units.
                    turnover = int(row["acml_tr_pbmn"]) * 1_000_000
                    volume = int(row["acml_vol"])
                    change_rate = float(row["prdy_ctrt"])
                    name = str(row["iem_nm"]).lstrip("* ").strip()
                    if price <= 0 or turnover < 0 or volume < 0 or not name:
                        raise ValueError
                    if not (-100 <= change_rate <= 1000):
                        raise ValueError
                except (KeyError, TypeError, ValueError, OverflowError):
                    raise NamuhUnavailable("나무 종목 시세 필드 확인 실패") from None
                quote = self.get_quote(symbol)
                items.append(
                    {
                        "symbol": symbol,
                        "name": name,
                        "price_won": price,
                        "change_percent": change_rate,
                        "turnover_won": turnover,
                        "volume": volume,
                        "last_trade_at": quote.as_of if quote else None,
                        "quote_live": bool(
                            quote
                            and 0 <= (checked_at - quote.as_of).total_seconds() <= 15
                        ),
                    }
                )
            self._ranking_cache = {
                "provider": "namuh_krx",
                "scope": "registered_symbols_only",
                "symbols": list(self.symbols),
                "checked_at": checked_at,
                "items": sorted(items, key=lambda item: item["turnover_won"], reverse=True),
            }
            self._ranking_cached_at = time.monotonic()
            return self._ranking_cache

    def status(self):
        result = super().status()
        result["provider"] = "나무 PLUG"
        result["last_error"] = self.last_error
        latest = result["last_trade_at"]
        if (
            result["state"] == "receiving"
            and latest
            and datetime.now(UTC) - latest > timedelta(seconds=15)
        ):
            result.update(state="stale", message="최신 시세 대기 · 주문 전 시세 재확인 필요")
        return result

    def load_session(self, token, symbol):
        status, result = _post(
            PERIOD_PATH,
            token=token,
            body={
                "Input_0": {
                    "market_cd": "KRX",
                    "iem_cd": symbol,
                    "view_main_yn": "Y",
                    "gubun": "1",
                    "array_cnt": "1",
                    "maxavg": "0",
                    "edate": datetime.now(KST).strftime("%Y%m%d"),
                }
            },
        )
        if status == 401:
            self.tokens.invalidate()
        if status != 200:
            raise NamuhUnavailable(f"나무 영업일 조회 통신 실패 (HTTP {status})")
        return market_session(result)

    def accept(self, raw, received_at):
        self.accept_trades(parse_trade(json.loads(raw), self.sessions, received_at), received_at)

    async def run(self):
        from websockets.asyncio.client import connect

        if not self.settings.nhplug_app_key or not self.settings.nhplug_app_secret:
            self.state = "waiting_credentials"
            return
        delay = 5
        while True:
            try:
                self.state = "connecting"
                token = await asyncio.to_thread(self.tokens.get)
                sessions = {}
                for symbol in self.symbols:
                    sessions[symbol] = await asyncio.to_thread(self.load_session, token, symbol)
                    await asyncio.sleep(0.25)
                self.sessions = sessions
                async with connect(
                    WS_URL,
                    ssl=tls_context(),
                    ping_interval=None,
                    logger=socket_logger,
                    open_timeout=10,
                    close_timeout=5,
                    max_size=1_000_000,
                ) as ws:
                    self.reset_connection(datetime.now(UTC))
                    self.state = "subscribing"
                    registered = set()
                    sent = []
                    connection_day = datetime.now(KST).date()
                    try:
                        for symbol in self.symbols:
                            await ws.send(self.subscription(token, symbol, "1"))
                            sent.append(symbol)
                            await asyncio.sleep(0.15)
                        while True:
                            raw = await asyncio.wait_for(ws.recv(), timeout=90)
                            if (
                                datetime.now(KST).date() != connection_day
                                or time.time() >= self.tokens.expiry - 60
                            ):
                                raise NamuhUnavailable("영업일 또는 인증 갱신을 위한 재연결")
                            message = json.loads(raw)
                            header = message.get("header", {})
                            if "rsp_cd" in header or "tr_type" in header:
                                if header.get("rsp_cd") != "00000" or header.get("tr_cd") != "oc":
                                    raise NamuhUnavailable(
                                        "나무 시세 구독 실패: 권한·동시 접속 확인 필요"
                                    )
                                keys = message.get("body", {}).get("tr_key", [])
                                if header.get("tr_type") != "1" or not isinstance(keys, list):
                                    raise NamuhUnavailable("나무 시세 구독 응답 형식 확인 실패")
                                registered.update(k for k in keys if k in self.symbols)
                                if registered == set(self.symbols):
                                    self.state = "subscribed"
                                    self.last_error = None
                            else:
                                if header.get("tr_key") not in registered:
                                    raise NamuhUnavailable("구독 확인 전 데이터 수신")
                                self.accept(raw, datetime.now(UTC))
                                self.last_error = None
                                delay = 5
                    finally:
                        for symbol in sent:
                            try:
                                await asyncio.wait_for(
                                    ws.send(self.subscription(token, symbol, "2")), 2
                                )
                                await asyncio.sleep(0.15)
                            except Exception:
                                break
            except NamuhAuthRejected as exc:
                self.reset_connection()
                self.state = "auth_failed"
                self.last_error = str(exc)
                return  # Do not repeatedly submit rejected credentials.
            except asyncio.CancelledError:
                self.reset_connection()
                self.state = "stopped"
                raise
            except Exception as exc:
                self.reset_connection()
                self.state = "reconnecting"
                self.last_error = (
                    str(exc)
                    if isinstance(exc, NamuhUnavailable)
                    else "시세 연결 오류: " + type(exc).__name__
                )
                logger.warning("Namuh market feed unavailable; retry scheduled")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)

    @staticmethod
    def subscription(token, symbol, action):
        return json.dumps(
            {
                "header": {"token": token, "tr_type": action},
                "body": {"tr_cd": "oc", "tr_key": symbol},
            }
        )

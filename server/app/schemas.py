import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,11}$")]
SymbolCode = Annotated[str, Field(pattern=r"^[A-Z0-9.]{1,16}$")]


class CheckDismiss(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=1000)


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class SessionResponse(BaseModel):
    access_token: str
    user_id: str


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: SymbolCode
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0, le=1_000_000, strict=True)
    limit_price_won: Money
    order_type: Literal["limit"] = "limit"
    pilot_enabled: bool = Field(strict=True)
    plan_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("limit_price_won")
    @classmethod
    def price_limit(cls, value: str) -> str:
        if int(value) > 1_000_000_000:
            raise ValueError("price exceeds supported range")
        return value


class Submit(Draft):
    check_id: str = Field(min_length=1, max_length=36)

    warning_acknowledged: bool = Field(default=False, strict=True)
    high_risk_acknowledged: bool = Field(default=False, strict=True)
    trade_reason: str = Field(default="", max_length=1000)

    def draft_dict(self) -> dict:
        return {field: getattr(self, field) for field in Draft.model_fields}


class CheckResponse(BaseModel):
    check_id: str
    allowed: bool
    messages: list[str]
    expires_at: datetime
    analysis: dict = Field(default_factory=dict)


class Receipt(BaseModel):
    order_id: str
    symbol: str
    status: Literal["accepted", "rejected", "cancelled", "filled"]
    reason: str | None = None
    mode: Literal["paper"] = "paper"


class QuoteResponse(BaseModel):
    symbol: str
    name: str
    price_won: str
    as_of: datetime
    sequence: int
    source: str


class WatchlistResponse(BaseModel):
    items: list[QuoteResponse]
    market_data_mode: str


class OrderList(BaseModel):
    items: list[Receipt]


class TicketResponse(BaseModel):
    ticket: str


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_limit_won: int = Field(gt=0, le=1_000_000_000, strict=True)
    daily_loss_limit_won: int = Field(gt=0, le=1_000_000_000, strict=True)
    cooldown_seconds: int = Field(ge=0, le=86400, strict=True)
    trading_rules: str = Field(max_length=2000)
    trading_paused: bool = Field(default=False, strict=True)


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: SymbolCode
    side: Literal["buy", "sell"]
    entry_condition: str = Field(min_length=1, max_length=1000)
    stop_loss_won: int | None = Field(default=None, gt=0, le=1_000_000_000, strict=True)
    max_amount_won: int = Field(gt=0, le=1_000_000_000, strict=True)
    split_order: bool = Field(default=False, strict=True)

    entry_min_won: int | None = Field(default=None, gt=0, le=1_000_000_000, strict=True)
    entry_max_won: int | None = Field(default=None, gt=0, le=1_000_000_000, strict=True)

    @model_validator(mode="after")
    def ordered_range(self):
        if (
            self.entry_min_won is not None
            and self.entry_max_won is not None
            and self.entry_min_won > self.entry_max_won
        ):
            raise ValueError("minimum price must not exceed maximum")
        return self


class Signup(Login):
    password: str = Field(min_length=12, max_length=256)
    password_confirmation: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("올바른 이메일을 입력하세요.")
        return value

    @model_validator(mode="after")
    def confirm(self):
        if self.password != self.password_confirmation:
            raise ValueError("비밀번호 확인이 일치하지 않습니다.")
        return self


class JournalNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=2000)


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    symbol: SymbolCode
    fast_period: int = Field(default=5, ge=2, le=100)
    slow_period: int = Field(default=20, ge=3, le=200)
    enabled: bool = True

    @model_validator(mode="after")
    def periods(self):
        if not self.name.strip() or self.fast_period >= self.slow_period:
            raise ValueError("전략명과 단기 < 장기 이동평균 기간을 확인하세요.")
        self.name = self.name.strip()
        return self


class BacktestRequest(BaseModel):
    dataset_id: str | None = Field(default=None, min_length=1, max_length=36)
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=32)
    start: datetime
    end: datetime
    initial_cash_won: int = Field(default=10_000_000, ge=10_000, le=100_000_000_000)
    fee_bps: int = Field(default=2, ge=0, le=100)
    slippage_bps: int = Field(default=5, ge=0, le=500)

    @model_validator(mode="after")
    def dates(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("시간대가 포함된 시작 < 종료 시각이 필요합니다.")
        if (self.end - self.start).days > 366:
            raise ValueError("한 번에 최대 366일까지 조회할 수 있습니다.")
        return self


class AutomationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)
    budget_won: int = Field(default=500_000, ge=10_000, le=100_000_000, strict=True)


class DatasetUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    symbol: SymbolCode
    provider: str = Field(min_length=1, max_length=100)
    data_kind: Literal["historical", "synthetic"]
    csv_text: str = Field(min_length=1, max_length=3_000_000)

    @field_validator("name", "provider")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("이름과 출처를 입력하세요.")
        return value

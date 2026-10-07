from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,11}$")]
SymbolCode = Annotated[str, Field(pattern=r"^[A-Z0-9.]{1,16}$")]


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

    @field_validator("limit_price_won")
    @classmethod
    def price_limit(cls, value: str) -> str:
        if int(value) > 1_000_000_000:
            raise ValueError("price exceeds supported range")
        return value


class Submit(Draft):
    check_id: str = Field(min_length=1, max_length=36)

    def draft_dict(self) -> dict:
        return self.model_dump(exclude={"check_id"})


class CheckResponse(BaseModel):
    check_id: str
    allowed: bool
    messages: list[str]
    expires_at: datetime


class Receipt(BaseModel):
    order_id: str
    symbol: str
    status: Literal["accepted", "rejected", "cancelled"]
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

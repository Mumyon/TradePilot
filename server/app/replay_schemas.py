from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCreate(Strict):
    dataset_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=100)
    replay_from: datetime
    event_key: Literal["custom", "covid_2020", "selloff_2024"] = "custom"
    source_url: str = Field(default="", max_length=500)


class ReplayPlan(Strict):
    side: Literal["buy", "sell"] = "buy"
    entry_min_won: int = Field(gt=0, le=1_000_000_000)
    entry_max_won: int = Field(gt=0, le=1_000_000_000)
    max_amount_won: int = Field(default=1_000_000, gt=0, le=100_000_000)
    stop_loss_won: int | None = Field(default=None, gt=0, le=1_000_000_000)
    split_order: bool = False
    entry_condition: str = Field(default="사전 등록 가격 범위 내 거래", max_length=500)

    @model_validator(mode="after")
    def bounds(self):
        if self.entry_min_won > self.entry_max_won:
            raise ValueError("계획 최소가가 최대가보다 큽니다.")
        return self


class Start(Strict):
    request_id: str = Field(min_length=8, max_length=64)
    pilot_enabled: bool | None = Field(default=None, strict=True)
    randomize_order: bool = Field(default=False, strict=True)
    plan: ReplayPlan | None = None
    paired_run_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def allocation(self):
        if self.randomize_order:
            if self.pilot_enabled is not None or self.paired_run_id is not None:
                raise ValueError(
                    "무작위 배정은 첫 실험에서만 사용하며 조건을 직접 지정할 수 없습니다."
                )
        elif self.pilot_enabled is None:
            raise ValueError("Pilot ON/OFF 조건을 지정하거나 순서 무작위 배정을 요청하세요.")
        return self


class Action(Strict):
    request_id: str = Field(min_length=8, max_length=64)
    revision: int = Field(ge=0, strict=True)
    action: Literal["advance", "check", "presented", "submit", "defer", "close", "cancel", "finish"]
    side: Literal["buy", "sell"] = "buy"
    quantity: int = Field(default=1, gt=0, le=1_000_000, strict=True)
    limit_price_won: int = Field(default=1, gt=0, le=1_000_000_000, strict=True)
    check_id: str | None = Field(default=None, max_length=36)
    order_id: str | None = Field(default=None, max_length=36)
    reason: str = Field(default="", max_length=1000)
    warning_acknowledged: bool = Field(default=False, strict=True)
    high_risk_acknowledged: bool = Field(default=False, strict=True)

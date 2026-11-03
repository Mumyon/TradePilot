from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr
    market_data_mode: Literal["disabled", "demo"] = "disabled"
    prediction_model_path: str | None = None
    orders_halted: bool = False
    paper_worker_enabled: bool = True
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    ws_ticket_ttl_seconds: int = Field(default=30, ge=1, le=60)
    quote_max_age_seconds: int = Field(default=15, ge=1, le=300)
    order_check_ttl_seconds: int = Field(default=60, ge=1, le=300)
    allowed_origins: list[str] = []
    ai_review_enabled: bool = False
    ai_review_local_only: bool = True
    chatgpt_credentials_dir: Path = Path(".demo/chatgpt")

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: SecretStr
    market_data_mode: Literal["disabled", "demo", "kis", "namuh", "toss"] = "disabled"
    kis_app_key: SecretStr | None = None
    kis_app_secret: SecretStr | None = None
    kis_symbols: list[str] = Field(default=["005930", "000660"], min_length=1, max_length=20)

    nhplug_app_key: SecretStr | None = None
    nhplug_app_secret: SecretStr | None = None
    nhplug_symbols: list[str] = Field(default=["005930", "000660"], min_length=1, max_length=20)
    nhplug_token_cache_dir: Path = Path(".paper-market/namuh-tokens")
    toss_client_id: SecretStr | None = None
    toss_client_secret: SecretStr | None = None
    toss_ranking_count: int = Field(default=100, ge=1, le=100)

    @field_validator("kis_symbols", "nhplug_symbols")
    @classmethod
    def validate_symbols(cls, symbols):
        if len(set(symbols)) != len(symbols) or any(
            len(s) != 6 or not s.isascii() or not s.isdigit() for s in symbols
        ):
            raise ValueError("Market symbols must be unique six-digit codes")
        return symbols

    prediction_model_path: str | None = None
    prediction_model_directory: Path | None = None
    paper_test_date: date | None = None
    orders_halted: bool = False
    paper_worker_enabled: bool = True
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    ws_ticket_ttl_seconds: int = Field(default=30, ge=1, le=60)
    quote_max_age_seconds: int = Field(default=15, ge=1, le=300)
    order_check_ttl_seconds: int = Field(default=300, ge=1, le=300)
    allowed_origins: list[str] = []
    ai_review_enabled: bool = False
    ai_review_local_only: bool = True
    chatgpt_credentials_dir: Path = Path(".demo/chatgpt")
    ai_review_provider: Literal["chatgpt_subscription", "openai_api"] = "chatgpt_subscription"
    openai_api_key: SecretStr | None = None
    local_openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"
    web_build_dir: Path | None = None
    naver_news_client_id: SecretStr | None = None
    naver_news_client_secret: SecretStr | None = None
    dart_api_key: SecretStr | None = None

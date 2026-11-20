"""Read-only market feed on the existing TradePilot paper account database."""

import argparse
import os
from pathlib import Path

import pgserver
import uvicorn
from alembic import command
from alembic.config import Config

from app.api import create_app
from app.config import Settings
from app.db import make_database
from app.logging_config import logging_config


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["namuh", "kis", "toss"], default="namuh")
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--ai-profile", choices=["local", "web"])
    parser.add_argument("--disable-ai", action="store_true")
    args = parser.parse_args()
    provider = args.provider
    # Reuse the established TradePilot app/account DB. Broker keys only enable quotes;
    # they never enable brokerage account access or orders.
    settings = Settings(
        database_url="postgresql://unused",
        market_data_mode=provider,
        paper_worker_enabled=True,
        ai_review_enabled=not args.disable_ai,
        order_check_ttl_seconds=300,
        _env_file=root
        / {
            "namuh": ".env.namuh",
            "kis": ".env.market",
            "toss": ".env",
        }[provider],
    )
    if args.ai_profile == "local":
        settings.openai_api_key = settings.local_openai_api_key
        settings.ai_review_provider = (
            "openai_api" if settings.openai_api_key else "chatgpt_subscription"
        )
        settings.ai_review_local_only = True
    elif args.ai_profile == "web":
        settings.ai_review_provider = "openai_api"
    if provider == "namuh":
        if not settings.nhplug_app_key or not settings.nhplug_app_secret:
            raise SystemExit("먼저 ./tool/configure_namuh.sh 로 키를 로컬에 설정하세요.")
    elif provider == "kis" and (not settings.kis_app_key or not settings.kis_app_secret):
        raise SystemExit("server/.env.market에 KIS 키를 로컬에 설정하세요.")
    elif provider == "toss" and (not settings.toss_client_id or not settings.toss_client_secret):
        raise SystemExit("server/.env에 토스 Open API 키를 로컬에 설정하세요.")
    if provider == "toss" and not (
        settings.prediction_model_directory or settings.prediction_model_path
    ):
        settings.prediction_model_directory = root / "models" / "toss"
    folder = args.data_dir or root / (".paper-market/kis" if provider == "kis" else ".demo")
    if args.data_dir is not None:
        settings.chatgpt_credentials_dir = folder / "chatgpt"
    settings.nhplug_token_cache_dir = root / ".paper-market" / "namuh-tokens"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    postgres = pgserver.get_server(folder / "postgres", cleanup_mode="stop")
    engine = None
    try:
        url = postgres.get_uri().replace("postgresql:", "postgresql+psycopg:", 1)
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config("alembic.ini"), "head")
        engine, sessions = make_database(url)
        settings.database_url = type(settings.database_url)(url)
        print(f"실제 KRX 시세 · 가상 자금/모의 체결: http://127.0.0.1:{args.port}", flush=True)
        print(f"AI 연결: {settings.ai_review_provider}", flush=True)
        print("TradePilot 계정·모의잔고를 사용합니다. 종료: Ctrl+C", flush=True)
        uvicorn.run(
            create_app(settings, sessions),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_config=logging_config(),
        )
    finally:
        if engine is not None:
            engine.dispose()
        postgres.cleanup()


if __name__ == "__main__":
    main()

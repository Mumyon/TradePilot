"""Local paper demonstration, isolated from .env and production DB.

State persists in server/.demo/postgres. Ctrl+C stops services without deleting it.
"""

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
    folder = root / ".demo"
    folder.mkdir(exist_ok=True)
    postgres = pgserver.get_server(folder / "postgres", cleanup_mode="stop")
    engine = None
    try:
        url = postgres.get_uri().replace("postgresql:", "postgresql+psycopg:", 1)
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config("alembic.ini"), "head")
        engine, sessions = make_database(url)
        # Explicit settings prevent environment flags from turning off demo checks.
        settings = Settings(
            database_url=url,
            market_data_mode="demo",
            orders_halted=False,
            prediction_model_path=None,
            paper_worker_enabled=True,
            ai_review_enabled=os.getenv("AI_REVIEW_ENABLED", "true").lower() == "true",
            ai_review_local_only=True,
            chatgpt_credentials_dir=folder / "chatgpt",
            _env_file=None,
        )
        print("TradePilot 로컬 모의투자: http://127.0.0.1:18081", flush=True)
        print("앱에서 회원가입하세요. 가상 시세/가상 자금만 사용합니다. 종료: Ctrl+C", flush=True)
        uvicorn.run(
            create_app(settings, sessions),
            host="127.0.0.1",
            port=18081,
            access_log=False,
            log_config=logging_config(),
        )
    finally:
        if engine is not None:
            engine.dispose()
        postgres.cleanup()


if __name__ == "__main__":
    main()

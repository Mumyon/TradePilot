"""Disposable synthetic FOMO fixture for feedback_test.dart; never uses .env."""

import os
import tempfile
from datetime import timedelta

import pgserver
import uvicorn
from alembic import command
from alembic.config import Config

from app.api import create_app
from app.cli import create_user
from app.config import Settings
from app.db import make_database
from app.models import QuoteSample, now


def main():
    server = pgserver.get_server(
        tempfile.mkdtemp(prefix="tradepilot-ios-test-"), cleanup_mode="delete"
    )
    engine = None
    try:
        url = server.get_uri().replace("postgresql:", "postgresql+psycopg:", 1)
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config("alembic.ini"), "head")
        engine, sessions = make_database(url)
        with sessions.begin() as db:
            create_user(
                db, "integration@example.test", "integration-only-password", demo_holdings=True
            )
            # Controlled +4% scenario, maintained for a three-minute native test window.
            stamp = now() - timedelta(minutes=10)
            for seconds in range(0, 181, 5):
                db.add(
                    QuoteSample(
                        symbol="005930",
                        source="demo",
                        as_of=stamp + timedelta(seconds=seconds),
                        price_won=70000,
                    )
                )
        app = create_app(
            Settings(database_url=url, market_data_mode="demo", _env_file=None), sessions
        )
        uvicorn.run(app, host="127.0.0.1", port=18080, log_level="warning")
    finally:
        if engine is not None:
            engine.dispose()
        server.cleanup()


if __name__ == "__main__":
    main()

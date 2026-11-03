"""Disposable loopback-only server for the iOS integration test; never uses .env."""

import os
import tempfile

import pgserver
import uvicorn
from alembic import command
from alembic.config import Config

from app.api import create_app
from app.cli import create_user
from app.config import Settings
from app.db import make_database


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

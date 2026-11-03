import os
import tempfile
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.api import create_app
from app.cli import create_user
from app.config import Settings
from app.db import make_database


@pytest.fixture(scope="session")
def postgres_url():
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        import pgserver
    except ImportError:
        pytest.fail("Set TEST_DATABASE_URL or install uv sync --group postgres-test (Python 3.12)")
    server = pgserver.get_server(
        tempfile.mkdtemp(prefix="tradepilot-pg-test-"), cleanup_mode="delete"
    )
    try:
        yield server.get_uri().replace("postgresql:", "postgresql+psycopg:", 1)
    finally:
        server.cleanup()


@pytest.fixture
def database(postgres_url, monkeypatch):
    # Create/drop only our unique schema, never an existing application's tables.
    schema = "tp_test_" + uuid4().hex
    admin = create_engine(postgres_url)
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(postgres_url).update_query_dict({"options": f"-csearch_path={schema}"})
    url = scoped_url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine, sessions = make_database(url)
    try:
        yield url, sessions
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def service(database):
    url, sessions = database
    settings = Settings(
        database_url=url, market_data_mode="demo", paper_worker_enabled=False, _env_file=None
    )
    with sessions.begin() as db:
        user = create_user(db, "test@example.com", "test-password-123", demo_holdings=True)
        user.cooldown_seconds = 0  # Baseline tests isolate non-cooldown behavior.
        user_id = user.id
    app = create_app(settings, sessions)
    with TestClient(app) as client:
        login = client.post(
            "/v1/auth/login", json={"email": "test@example.com", "password": "test-password-123"}
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, sessions, user_id, settings

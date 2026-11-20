from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.models import User

FIELDS = {
    "order_limit_won",
    "daily_loss_limit_won",
    "cooldown_seconds",
    "trading_rules",
    "trading_paused",
}


def test_preferences_are_gone_and_old_order_limit_is_not_applied(service):
    client, sessions, uid, _ = service
    assert client.get("/v1/settings").status_code == 404
    assert client.put("/v1/settings", json={}).status_code == 404
    client.get("/v1/watchlist")
    draft = dict(
        symbol="005930",
        side="buy",
        quantity=20,
        limit_price_won="72800",
        order_type="limit",
        pilot_enabled=False,
    )
    check = client.post("/v1/orders/check", json=draft).json()
    assert check["allowed"], check
    receipt = client.post(
        "/v1/orders",
        headers={"Idempotency-Key": "no-deleted-limit"},
        json={**draft, "check_id": check["check_id"]},
    ).json()
    assert receipt["status"] == "accepted"
    assert client.post(f"/v1/orders/{receipt['order_id']}/cancel").json()["status"] == "cancelled"
    with sessions() as db:
        assert db.get(User, uid).cash_won == 10000000
        assert db.get(User, uid).reserved_won == 0
        columns = set(
            db.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'users'"
                )
            )
        )
        assert not columns & FIELDS


def test_migration_drops_personal_settings_preserving_money(database):
    _, sessions = database
    config = Config("alembic.ini")
    command.downgrade(config, "20261109_market_calendar")
    with sessions.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id,email,password_hash,enabled,cash_won,reserved_won,"
                "order_limit_won,daily_loss_limit_won,cooldown_seconds,"
                "trading_rules,trading_paused) "
                "VALUES ('settings-removal','settings@example.test','unused',true,1234567,12345,"
                "20000,30000,600,'old personal rules',true)"
            )
        )
    command.upgrade(config, "head")
    with sessions() as db:
        user = db.get(User, "settings-removal")
        assert user.cash_won == 1234567 and user.reserved_won == 12345
        columns = set(
            db.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'users'"
                )
            )
        )
        assert not columns & FIELDS

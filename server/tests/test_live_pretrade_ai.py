"""Optional real ChatGPT response; synthetic order in a disposable schema only."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.brokers.toss import TossMarketData, _rows
from app.config import Settings
from app.llm import chatgpt
from app.models import Quote, Symbol, User, now
from app.security import passwords
from app.services import ai_review


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_PRETRADE_AI") != "1", reason="explicit live opt-in required"
)
def test_live_subscription_pretrade_feedback_queue(database):
    root = Path(__file__).resolve().parents[1] / ".demo/chatgpt"
    profiles = [p for p in root.glob("*.json") if p.stem != "host"]
    assert len(profiles) == 1, "Select a local connected test profile first"
    uid = profiles[0].stem
    connection = chatgpt.connection(root, uid)
    provider = TossMarketData(Settings(_env_file=Path(__file__).resolve().parents[1] / ".env"))
    prices = _rows(provider._api("/api/v1/prices", {"symbols": "005930"}), "prices", "items")
    price = int(prices[0]["lastPrice"])
    url, sessions = database
    settings = Settings(
        database_url=url,
        market_data_mode="disabled",
        paper_worker_enabled=False,
        ai_review_enabled=True,
        order_check_ttl_seconds=300,
        ai_review_local_only=False,
        chatgpt_credentials_dir=root,
        _env_file=None,
    )
    with sessions.begin() as db:
        db.add(
            User(
                id=uid,
                email="synthetic-review@example.test",
                password_hash=passwords.hash("synthetic-test-password"),
            )
        )
        db.add(Symbol(symbol="005930", name="삼성전자"))
        db.flush()
        db.add(Quote(symbol="005930", price_won=price, as_of=now(), sequence=1, source="toss_kr"))
    # Keep worker deterministic: submit while disabled, then run exactly one job explicitly.
    settings.ai_review_enabled = False
    with TestClient(create_app(settings, sessions)) as client:
        login = client.post(
            "/v1/auth/login",
            json={"email": "synthetic-review@example.test", "password": "synthetic-test-password"},
        )
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        settings.ai_review_enabled = True
        check = client.post(
            "/v1/orders/check",
            json=dict(
                symbol="005930",
                side="buy",
                quantity=1,
                limit_price_won=str(price),
                order_type="limit",
                pilot_enabled=False,
            ),
        ).json()
        path = f"/v1/orders/check/{check['check_id']}/ai-feedback"
        assert client.get(path).json()["status"] == "ready"
        assert client.post(path, json={"consent": True}).json()["status"] == "pending"
        ai_review.process_next(sessions, settings, provider)
        result = client.get(path).json()
        if result["status"] != "available":
            from sqlalchemy import select

            from app.models import AIReview

            with sessions() as db:
                record = db.scalar(select(AIReview).where(AIReview.check_id == check["check_id"]))
                print({k: record.data.get(k) for k in ("error", "error_type", "error_reason")})
        assert result["status"] == "available", result.get("message")
        assert result["result"]["kind"] == "quant_web"
        assert result["result"]["body"]
        assert result["search"]["used"]
        assert result["coverage"] is None
        assert result["response_model"]
        output = (
            Path(__file__).resolve().parents[2]
            / "docs/verification/QUANT_WEB_RESPONSE_2026-11-09.md"
        )
        report = result["result"]
        lines = [
            "# 삼성전자 ChatGPT 정량 분석 실제 응답",
            "",
            "ChatGPT 직접 웹 검색 · 투자 기간/성향 미지정 · 주문 접수 없음",
            "",
            f"모델: {result['response_model']}, 응답 소요: {result['latency_ms']}ms",
            "",
            f"완료된 웹 검색: {result['search']['completed_calls']}회",
            "",
            report["body"], "",
        ]
        lines += [
            "",
            "## 웹 검색 실행 정보 및 출처",
            "",
            "```json",
            json.dumps(
                {
                    "search": result["search"],
                    "analysis_as_of": result["analysis_as_of"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
        output.write_text("\n".join(lines))
        print(
            {
                "status": result["status"],
                "requested_model": connection["model"],
                "response_model": result["response_model"],
                "latency_ms": result["latency_ms"],
            }
        )

"""Disposable native integration: synthetic market and mock OpenAI transport.

No credentials, no external requests, no demonstration DB changes.
"""

import json
import os
import tempfile

import httpx
import pgserver
import uvicorn
from alembic import command
from alembic.config import Config

from app.api import create_app
from app.config import Settings
from app.db import make_database
from app.llm import chatgpt


def main():
    postgres = pgserver.get_server(
        tempfile.mkdtemp(prefix="tradepilot-ai-ios-"), cleanup_mode="delete"
    )
    engine = None
    requests = []
    try:
        url = postgres.get_uri().replace("postgresql:", "postgresql+psycopg:", 1)
        os.environ["DATABASE_URL"] = url
        command.upgrade(Config("alembic.ini"), "head")
        engine, sessions = make_database(url)

        def handle(request):
            assert str(request.url) == chatgpt.RESOURCE + "/responses"
            body = json.loads(request.content)
            assert body["store"] is False and body["stream"] is True
            payload = json.loads(body["input"][0]["content"])
            assert set(payload) == {"schema", "facts"}
            requests.append(payload)
            text = json.dumps(
                dict(
                    observations=[
                        dict(
                            fact_id="rule_0",
                            interpretation="계획과 실제 주문 판단을 나란히 확인해 보세요.",
                            reflection_question=(
                                "다음 매수 전에 어떤 진입 조건을 확인할 수 있을까요?"
                            ),
                        )
                    ],
                    limitation=(
                        "자동검증 응답 대역입니다. 사람 대상 연구나 실제 모델 성능 결과가 아닙니다."
                    ),
                ),
                ensure_ascii=False,
            )
            result = dict(
                type="response.completed",
                response=dict(
                    id="mock-only-response",
                    model="mock-only-model",
                    status="completed",
                    output=[dict(type="message", content=[dict(type="output_text", text=text)])],
                    usage=dict(input_tokens=100, output_tokens=100),
                ),
            )
            return httpx.Response(200, content=("data: " + json.dumps(result) + "\n\n").encode())

        chatgpt.connection = lambda *_: dict(model="mock-only-model")
        chatgpt.access = lambda *_: dict(access_token="mock-only-token")
        chatgpt.client = lambda: httpx.Client(transport=httpx.MockTransport(handle))
        settings = Settings(
            database_url=url,
            market_data_mode="demo",
            ai_review_enabled=True,
            paper_worker_enabled=False,
            _env_file=None,
        )
        app = create_app(settings, sessions)

        @app.get("/__test__/stats")
        def stats():
            return dict(mock_requests=len(requests), external_calls=0)

        uvicorn.run(app, host="127.0.0.1", port=18080, log_level="warning", access_log=False)
    finally:
        if engine is not None:
            engine.dispose()
        postgres.cleanup()


if __name__ == "__main__":
    main()

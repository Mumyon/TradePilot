"""Bounded read-only connection check. No accounts or orders are requested."""

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from app.brokers.namuh import NamuhMarketData
from app.config import Settings


async def check():
    root = Path(__file__).resolve().parents[1]
    settings = Settings(
        database_url="postgresql://unused",
        market_data_mode="namuh",
        nhplug_token_cache_dir=root / ".paper-market" / "namuh-tokens",
        _env_file=root / ".env.namuh",
    )
    if not settings.nhplug_app_key or not settings.nhplug_app_secret:
        print("키 설정 대기: 프로젝트 루트에서 ./tool/configure_namuh.sh 를 실행하세요.")
        return 2
    feed = NamuhMarketData(settings)
    task = asyncio.create_task(feed.run())
    result = None
    try:
        for _ in range(30):
            await asyncio.sleep(1)
            result = feed.status()
            if result["state"] in ("subscribed", "receiving", "auth_failed"):
                break
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    success = result["state"] in ("subscribed", "receiving")
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "subscription_confirmed": success,
        "trade_received": result["state"] == "receiving",
        "status": result,
        "live_orders_enabled": False,
    }
    output = root / ".paper-market" / "namuh-connection-status.json"
    output.parent.mkdir(mode=0o700, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
    print(
        "나무 시세 구독 확인 완료" if success else "연결 확인 미완료: 키·권한·접속 환경 확인 필요"
    )
    print(
        "실제 체결 데이터 수신 확인"
        if report["trade_received"]
        else "실제 체결 데이터는 아직 미수신"
    )
    if not success:
        print(result["last_error"])
    print("실계좌 조회·실주문 호출: 없음")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))

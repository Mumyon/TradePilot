# TradePilot FastAPI 서버

Flutter 클라이언트의 REST·WebSocket 계약을 구현한 초기 서버입니다.
PostgreSQL에 계정·세션·관심종목·시세·주문 점검·모의주문을 저장합니다.
**증권사 API는 연결하지 않았습니다.** 연동 인터페이스와 교체 위치만 제공합니다.

## 실행: Docker Compose

Docker / Compose가 설치된 환경에서 `server/`로 이동합니다.

```sh
cp .env.compose.example .env
# .env의 POSTGRES_PASSWORD와 DATABASE_URL 비밀번호를 같은 값으로 수정
docker compose up --build -d
docker compose exec api python -m app.cli create-user --email your-email@example.com
```

계정 비밀번호는 터미널에서 숨김 입력합니다. 기본 모의 잔액은 10,000,000원,
1회 주문한도는 1,000,000원입니다. 사용자 생성은 로컬 관리 명령이며 공개 회원가입 API는 없습니다.
`--demo-holdings`를 추가하면 두 예시 종목을 각각 100주 보유한 테스트 계정을 만듭니다.
마이그레이션은 `migrate` 서비스가 성공한 후 API를 시작하는 방식입니다.

- Swagger: <http://localhost:8000/docs>
- OpenAPI: <http://localhost:8000/openapi.json>
- 생존 확인: <http://localhost:8000/health/live>
- DB·스키마 확인: <http://localhost:8000/health/ready>
- PostgreSQL은 Compose 내부 네트워크에서만 접근하고 데이터는 볼륨에 유지합니다.

## 실행: 로컬 Python + PostgreSQL

Python 3.12 이상, `uv`, 실행 중인 PostgreSQL이 필요합니다.

```sh
cp .env.example .env
# DATABASE_URL을 실제 로컬 DB 주소로 수정
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.cli create-user --email your-email@example.com
uv run python -m app.run
```

`python -m app.run`은 WebSocket 티켓이 서버 로그에 노출되지 않도록 필터를 적용합니다.
직접 `uvicorn app.main:app`을 실행하면 기본 핸드셰이크 로그에 query가 포함될 수 있으므로
이 프로젝트의 실행 모듈을 사용하세요. 프록시 로그에도 같은 query 마스킹 정책을 적용해야 합니다.

## 증권사 없이 클라이언트 확인

기본 `MARKET_DATA_MODE=disabled`는 신규 시세를 생성하지 않습니다. 시세가 없는 새 DB에서는
관심종목 응답이 비어 있고 주문 검사는 거절됩니다. 기존 저장 시세가 있다면 원래 기준 시각과
source를 유지하며 조회합니다. 오래된 시세를 최신으로 바꾸지 않습니다.

가상 시세로 통신을 확인하려면 `.env`에 `MARKET_DATA_MODE=demo`를 명시합니다.
Compose에서는 `docker compose up -d api`로 설정 변경을 반영하세요.
이 모드는 삼성전자·SK하이닉스 **고정 예시 가격**을 현재 가상 시각으로 공급하며,
시세 응답에 `source: "demo"`, 관심종목 응답에 `market_data_mode: "demo"`를 포함합니다.
AI는 어느 모드에서도 `unavailable`을 반환합니다.

현재 Flutter 클라이언트는 원격 API에 HTTPS/WSS를 요구합니다. 로컬 Python 서버를 앱과 연결할 때는
기기에서 신뢰하는 인증서와 접근 가능한 호스트를 준비하여 아래처럼 실행하거나 TLS 프록시를 사용합니다.
인증서 검증을 끄도록 클라이언트를 변경하지 않았습니다.

```sh
TLS_CERTFILE=/absolute/path/server.pem TLS_KEYFILE=/absolute/path/server-key.pem \
BIND_HOST=0.0.0.0 uv run python -m app.run
```

클라이언트 실행 인자: `--dart-define=DEMO_MODE=false --dart-define=API_BASE_URL=https://your-host:8000`.
안드로이드 에뮬레이터/실기기에서 `localhost`는 해당 기기를 의미하므로 서버 호스트 주소를 사용합니다.

## API

| 종류 | 경로 | 동작 |
|---|---|---|
| POST | `/v1/auth/login` | 이메일·비밀번호 → access_token·user_id |
| POST | `/v1/auth/logout` | 현재 서버 세션 폐기 |
| GET | `/v1/watchlist` | 사용자 관심종목 시세 |
| GET | `/v1/predictions/{symbol}` | AI 미연결 상태 |
| POST | `/v1/orders/check` | 시세 신선도·1회 한도·잔액·보유량 점검 |
| POST | `/v1/orders` | 최종 재검증·금액/수량 예약·모의주문 접수 |
| GET | `/v1/orders` | 본인 주문 최신 200건 |
| POST | `/v1/orders/{id}/cancel` | 모의 미체결 주문 취소·예약 해제 |
| POST | `/v1/ws-ticket` | 짧은 수명의 일회용 접속 티켓 |
| WS | `/v1/ws?ticket=...` | 관심종목 구독·시세·ping/pong |
| GET | `/v1/integrations/broker` | 증권사 기능 미연결 상태 |
| GET | `/v1/market/{symbol}/candles` | 차트 연동 자리 (`unavailable`) |

로그인 이외 `/v1` REST는 Bearer 인증이 필요합니다. 계정 비밀번호는 Argon2 해시,
세션·티켓은 원문 대신 SHA-256 해시로 저장합니다. WebSocket 티켓은 DB에서 원자적으로 소모하고,
연결 중에도 세션 만료·폐기를 검사합니다. WebSocket은 매 2초 DB/데모 시세를 조회하는 초기 구조이며
대규모 시세 중계 브로커나 분산 fan-out은 아직 없습니다.

## 주문 처리 범위

모의주문 **접수·취소**를 지원하며 자동 체결은 하지 않습니다. `accepted`는 `filled`가 아닙니다.
매수 금액·매도 수량을 예약하고 취소 시 한 번만 해제합니다. 서버에서 사용자 행을 잠근 뒤
동일 키 조회·최신 잔액 검사·예약·주문 기록을 한 트랜잭션으로 처리합니다.
DB 확정이 완료된 뒤에만 성공 응답을 전송합니다.
동일 사용자/Idempotency-Key는 기존 결과를 반환하고 본문이 바뀌면 409입니다.
동일 점검 ID를 새 주문 키로 다시 사용하는 것도 거절합니다.

금액은 정수 원화이며 API에서는 문자열입니다. 현재 수수료·부분 체결·손익 장부·일일 손실한도·
쿨다운·계획 예외·행동 탐지는 미구현입니다. `daily_loss_limit_won`은 후속 손익 장부를 위한
예약 필드이며 아직 집행하지 않습니다. TradePilot OFF여도 구현된 필수 검사들은 유지합니다.
ON이면 행동 분석 미연결 메시지를 표시하므로 위험이 없다고 오해하게 하지 않습니다.

주문 키는 현재 삭제하지 않습니다. 보존 기간을 정할 때 앱의 장기 미확인 주문 복원과 함께 설계해야 합니다.
현재 클라이언트 로그아웃은 로컬 토큰 삭제만 하므로 서버 즉시 폐기가 필요하면 위 logout API를 연결하세요.
운영 공개 전에는 로그인 시도 제한, 만료 세션·티켓 정리, 계정 관리, TLS 배포 등을 별도로 완성해야 합니다.

## 구조와 다음 연결 위치

```text
app/api.py                 REST / WebSocket / 인증 의존성
app/security.py            비밀번호·세션·일회용 티켓
app/models.py              PostgreSQL 테이블
app/services/market.py     시세 저장/조회, publish_quote 수신 지점
app/services/orders.py     서버 내부 모의주문 트랜잭션
app/services/predictions.py AI 결과 연결 자리
app/brokers/contracts.py   증권사 공통 인터페이스/정규화 모델
app/brokers/template.py    인증·시세·차트·잔고·주문·취소·체결 구현 자리
app/brokers/factory.py     어댑터 선택/주입 지점
migrations/               Alembic 버전 관리
tests/                    실제 PostgreSQL 기반 통합 검증
```

세부 작업 순서는 [증권사 연결 안내](docs/broker-integration.md)를 참고하세요.

## 재검증

```sh
uv sync --frozen --group postgres-test --python 3.12
uv run --group postgres-test pytest -q
uv run ruff check .
uv run ruff format --check .
```

`postgres-test` 그룹은 macOS/Linux 테스트용 PostgreSQL 바이너리를 제공합니다. 테스트는 임시 서버와
무작위 전용 스키마를 사용하고 종료 시 제거합니다. 외부 테스트 DB를 사용할 경우
`TEST_DATABASE_URL=postgresql+psycopg://...`을 지정하면 됩니다. 테스트 계정에는 스키마 생성 권한이 필요합니다.
이 테스트 도구는 Docker 운영 이미지에 포함되지 않습니다.

검증 상태: [verification.md](docs/verification.md).

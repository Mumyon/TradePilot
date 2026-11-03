# 1~3단계 개발 및 재검증 결과

작성: 2026-10-18 (Asia/Seoul)

## 완료 범위

1. 계좌·보유종목·잔고·평가손익 조회, 사용자별 거래 설정 및 매매 계획 저장, 등록 종목 검색과 관심종목 추가/삭제.
2. PostgreSQL OHLCV 저장/조회, 1분·5분·15분·1시간·1일봉, 출처·기준 시각·지연 표시, 서버 캔들 기반 Flutter 차트. 계좌·주문은 5초, 차트는 30초 갱신; 시세는 기존 WebSocket 사용.
3. 지정가 모의 체결, 수수료·원가·평균 매입가·실현손익 계산, 예약금/예약 수량 해제, 주문 취소, 중복 체결 방지 및 체결 장부.

## 앱에서 확인하는 위치

서버 연결 모드에서 **전체 메뉴 → 계좌 카드 → 계좌 · 거래 설정 · 관심종목 관리**를 누르세요.
계좌 / 거래 설정 / 관심종목 / 매매 계획 / 주문·체결 탭이 있습니다.
관심종목 화면의 검색 아이콘도 서버 종목 관리로 연결됩니다. 차트의 시간 구간을 누르면 해당 캔들을 다시 조회합니다.
매매일지의 전체 보기는 주문·체결 관리로 연결됩니다.

`DEMO_MODE=true`는 기존 화면 시연용 메모리 저장소입니다. 새 영속 계좌·설정·체결 기능은 `DEMO_MODE=false`로 서버에 연결해야 합니다.

## 구현 정책과 한계

- 증권사 API는 미연결. 서버 `MARKET_DATA_MODE=demo`에서 삼성전자·SK하이닉스 두 종목의 고정 현재가와 결정론적 테스트 캔들을 생성합니다. 실제 거래소 가격/거래량이 아닙니다. 차트·계좌는 이 입력에 따른 모의 결과입니다.
- 접수 이후의 새로운 시세만 체결에 사용합니다. 매수는 시세 ≤ 지정가, 매도는 시세 ≥ 지정가일 때 그 시세 가격으로 전량 체결합니다. 거래량 제한·부분 체결·호가 대기열·세금·슬리피지는 모델링하지 않습니다.
- 모의 수수료는 편도 0.015%, 주문별 원 단위 올림입니다. 실제 증권사 수수료 규정이 아닙니다. 매수 예약금에는 수수료를 포함합니다. 평균 매입가에는 매수 수수료를 포함하며 원 단위 내림으로 표시합니다.
- 매도 원가는 보유 원가를 수량 비례로 배분합니다. 매도 순실현손익 = 매도대금 - 매도 수수료 - 배분 원가입니다.
- 기존 계정의 보유 원가는 알 수 없으므로 마이그레이션에서 NULL로 보존합니다. 원가 미확인 매도는 손익을 임의 계산하지 않으며 누적 실현손익에 일부 미확인 표시가 붙습니다. 새 `--demo-holdings` 계정은 명시된 초기 테스트 원가가 있습니다.
- 기존 미체결 주문·예약금은 유지됩니다. 이전 주문은 원금만 예약되어 있어 체결 시 추가 수수료 여력이 없으면 대기 사유를 표시합니다. 강제 취소하지 않습니다.
- 거래 설정 중 1회 주문한도는 주문 점검에 적용됩니다. 일일 손실한도·쿨다운·거래 원칙·계획 자동 평가는 4단계 범위이며 현재 저장만 합니다. 매매 계획은 등록 시각과 함께 별도 이력으로 보존합니다.
- AI·행동 분석·자동매매·실계좌 주문은 이번 범위에 포함되지 않습니다.
- 체결 worker는 FastAPI 프로세스가 살아 있는 동안 2초 간격으로 동작합니다. 서버 종료 중에는 체결되지 않으며 재시작 후 최신 시세로 미체결 주문을 다시 평가합니다. 상시 실행 서버를 기준으로 구현했으며 서버리스 배포 전 worker 분리가 필요합니다.

## 데이터 이전 및 실행

기존 개발 DB에는 이번 작업 중 마이그레이션을 적용하지 않았습니다. 테스트는 별도의 임시 PostgreSQL을 사용했습니다.

Docker Desktop 실행 후:

```sh
cd /Users/mumyon/Documents/TradePilot/server
/Applications/Docker.app/Contents/Resources/bin/docker compose up --build -d
/Applications/Docker.app/Contents/Resources/bin/docker compose ps
```

`migrate` 서비스가 `20261018_paper` 스키마로 갱신합니다. `.env`의 `MARKET_DATA_MODE=demo`를 사용해야 증권사 없이 테스트 시세가 공급됩니다. 로컬 Python 실행 시에는 서버 디렉터리에서 `.venv/bin/alembic upgrade head` 후 `.venv/bin/python -m app.run`을 실행합니다.

HTTPS 서버 또는 새 Cloudflare 터널 주소로 앱을 실행합니다. 이전 임시 터널 주소는 재사용하지 마세요.

```sh
cd /Users/mumyon/Documents/TradePilot/client
./tool/flutterw run -d 415A659E-9A09-4C35-BABB-2FA140F9BDA8 \
  --dart-define=DEMO_MODE=false \
  --dart-define=API_BASE_URL=https://YOUR-CURRENT-SERVER
```

## 검증 결과

- 실제 임시 PostgreSQL 기반 서버 테스트: 26개 통과. 기존 인증·WebSocket·주문 테스트 포함.
- 별도 100건 주문 수명주기 시나리오: 체결 80건, 취소 20건, 재요청 후 주문 수 100건 유지, 중복 체결 0건, 잔고/예약금 확인.
- 동시 worker 체결 및 취소·체결 경쟁, 수수료 잔액 부족, 시세 지연, 원가 미확인, 체결 트랜잭션 롤백, 계정 격리, 기존 스키마 이전 검증.
- Flutter 단위·위젯 테스트: 24개 통과. 설정 검증/저장, 관심종목 추가·삭제·검색, 계획 등록, 취소, 캔들 상태 표시 및 기존 화면 테스트 포함.
- iPhone 17 / iOS 26.5 통합 테스트: 실제 FastAPI·임시 PostgreSQL로 로그인 → 주문 점검 → 접수 → worker 체결 → 동일 키 재조회 → 잔액 확인 → 차트 → 설정 저장 검증.
- Python Ruff 및 Flutter 정적 분석 확인. 서버 테스트에 Starlette/httpx 연동의 향후 사용 중단 경고 1건이 있으나 테스트 실패는 없습니다.
- Android는 이번 변경의 기기 실행 검증을 수행하지 않았습니다. iOS 결과를 Android 검증 결과로 간주하지 않습니다.

## 재검증 명령

```sh
cd /Users/mumyon/Documents/TradePilot/server
.venv/bin/pytest -q
.venv/bin/ruff check app migrations tests tool
```

```sh
cd /Users/mumyon/Documents/TradePilot/client
./tool/flutterw analyze
./tool/flutterw test
```

실제 iOS 통합 테스트는 별도 터미널에서 임시 서버를 먼저 실행합니다. 개발 DB를 사용하지 않으며 서버 종료 시 임시 DB를 정리합니다.

```sh
cd /Users/mumyon/Documents/TradePilot/server
PYTHONPATH=. .venv/bin/python tool/serve_integration.py
```

```sh
cd /Users/mumyon/Documents/TradePilot/client
./tool/flutterw drive --driver=test_driver/paper_driver.dart \
  --target=integration_test/paper_trading_test.dart \
  -d 415A659E-9A09-4C35-BABB-2FA140F9BDA8
```

통합 테스트는 loopback 전용 테스트 서버만 HTTP로 호출합니다. 배포 앱의 HTTPS 요구 설정은 변경하지 않았습니다. 화면 캡처는 `client/docs/paper-review/`에 저장됩니다.

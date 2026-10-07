# TradePilot

- [`서버 + 앱 테스트 실행 안내`](RUN_TEST_GUIDE.md): 처음 설치부터 로그인·모의 주문 확인까지
- [`client/`](client/README.md): Flutter/Dart Android·iOS 클라이언트 구성 및 실행 안내
- [`server/`](server/README.md): FastAPI·PostgreSQL 서버 실행 및 검증 안내
- [`증권사 연결 위치`](server/docs/broker-integration.md): 시세·잔고·주문·체결 어댑터 구현 자리
- [`client/docs/api-contract.md`](client/docs/api-contract.md): 예정된 FastAPI 서버의 REST·WebSocket 계약
- [`client/docs/architecture.mmd`](client/docs/architecture.mmd): Mermaid 클라이언트 구조도
- [`client/docs/verification.md`](client/docs/verification.md): 검증 결과·재검증 체크리스트
- `UI_figma/`: 기존 디자인 및 프로토타입 자료

클라이언트는 Flutter, 서버는 FastAPI, DB는 PostgreSQL입니다. 증권사 API는 아직 연결하지 않았습니다.

> 최신 변경(2026-10-20): [실제 과거 5분봉 적용 보고서](HISTORICAL_DATA_REPORT.md). 삼성전자 2026-07-29·08-21·10-13·10-15의 Yahoo Finance 실제 OHLCV를 모의투자 기본 사례로 연결했습니다. 2020/2024 사건의 실제 5분봉은 여전히 확보 대기입니다. 아래의 “합성 사례만 있음” 설명은 이전 시점 기록입니다.

> 2026-10-20 최신: [로컬 AI·과거 장세 모의실험 사용 및 연구 안내](REPLAY_RESEARCH_REPORT.md). 하단 모의투자 탭이 실험 화면으로 연결됩니다. 기존 전략/계좌는 `기존 모의계좌 · 전략`에서 접근합니다.

# 최신 확장: CSV 연구 데이터

[등록·백테스트 연결 보고서](DATASET_REPORT.md) · 앱 경로: 모의투자 → 백테스트 → CSV 등록 · 내 데이터 선택.

# 최신 확장: 모의 자동매매

[구현·검증 보고서](AUTOMATION_REPORT.md) · 앱 경로: 모의투자 → 백테스트 → 모의 자동매매 관리.

# 최신 확장: 전략 관리·백테스트

[구현·검증 보고서](BACKTEST_REPORT.md) · 앱 경로: 모의투자 → 백테스트.

> **최신 v3 시연:** [Docker 없이 iPhone 앱 실행](DEMO_GUIDE.md) · [최종 구현·검증 보고서](V3_COMPLETION_REPORT.md). 아래 단계별 기록은 작성 당시 상태입니다.

> 최신 4~6단계 개발·검증: [결과 보고서](STAGES_4_6_REPORT.md). AI는 실제 데이터 미확보로 [CSV 학습 경로](server/docs/csv-training.md)를 준비한 상태입니다.

# TradePilot

- [2026-10-18 · 계좌/차트/모의 체결 개발 결과 및 실행 안내](DEVELOPMENT_REPORT_2026-10-18.md)
- [원본 JSON 디자인 적용·실행 안내](client/docs/design-implementation.md)

- [`서버 + 앱 테스트 실행 안내`](RUN_TEST_GUIDE.md): 처음 설치부터 로그인·모의 주문 확인까지
- [`client/`](client/README.md): Flutter/Dart Android·iOS 클라이언트 구성 및 실행 안내
- [`server/`](server/README.md): FastAPI·PostgreSQL 서버 실행 및 검증 안내
- [`증권사 연결 위치`](server/docs/broker-integration.md): 시세·잔고·주문·체결 어댑터 구현 자리
- [`client/docs/api-contract.md`](client/docs/api-contract.md): 예정된 FastAPI 서버의 REST·WebSocket 계약
- [`client/docs/architecture.mmd`](client/docs/architecture.mmd): Mermaid 클라이언트 구조도
- [`client/docs/verification.md`](client/docs/verification.md): 검증 결과·재검증 체크리스트
- `UI_figma/`: 기존 디자인 및 프로토타입 자료

클라이언트는 Flutter, 서버는 FastAPI, DB는 PostgreSQL입니다. 증권사 API는 아직 연결하지 않았습니다.

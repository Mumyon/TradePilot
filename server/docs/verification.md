# 서버 검증 기록

2026-10-08 · Python 3.12 · 실제 임시 PostgreSQL 사용.

- Alembic 초기 마이그레이션 생성 및 PostgreSQL 적용 성공.
- PostgreSQL 기반 API/WebSocket 테스트 16개 통과.
- Ruff 정적 검사 및 포맷 검사 통과.
- 중복 주문 키·만료 후 재조회·다른 본문 충돌·점검 ID 재사용 확인.
- 같은 키 동시 요청 4건에서 주문/예약 1건 확인.
- 다른 키 동시 요청에서 잔액 초과 예약 방지 확인.
- DB 확정 실패 시 성공 응답을 보내지 않고 주문·예약을 롤백하는 것 확인.
- 계정 간 주문 조회·취소·점검 ID 접근 차단 확인.
- 시세 지연·잔액 변화·매도 가능 수량·TradePilot OFF 검사 확인.
- WebSocket 구독·quote·ping/pong·일회용/만료 티켓 확인.
- 증권사 미연결 기본 모드와 실주문 어댑터 차단 확인.

Docker/Compose 실행은 이 환경에 Docker가 없어 미검증입니다.
Flutter 실기기와 HTTPS/WSS 통합, 실제 증권사 API, 실계좌 주문은 아직 검증하지 않았습니다.
테스트의 PostgreSQL 바이너리는 개발 검증용이며 운영 Docker의 PostgreSQL 17 이미지와
동일 바이너리는 아닙니다. 운영 대상 버전에서도 배포 전 테스트하세요.

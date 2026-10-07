# FastAPI 연동 계약 초안

2026-10-08: `server/`에 이 계약을 따르는 FastAPI 서버를 구현했습니다.
서버의 PostgreSQL 기반 API/WebSocket 검증은 완료했으며 Flutter 실기기와 HTTPS/WSS 연결 검증은 남아 있습니다.
PostgreSQL에 앱이 직접 접속하지 않습니다. 서버의 현재 구현 범위는 `server/README.md`를 참고하세요.
서버는 모의주문 접수·취소만 구현했고 자동 체결·AI 예측·증권사 연동은 미구현입니다.

## 공통

- HTTPS origin + `/v1` 경로. `API_BASE_URL`에는 `/v1`을 붙이지 않습니다.
- 인증: `Authorization: Bearer <access_token>`. 토큰은 플랫폼 보안 저장소에 저장.
- 로그인 이외 REST는 인증 필수. 401은 토큰 삭제 후 재로그인. 자동 토큰 갱신은 아직 없음.
- 시간은 UTC ISO 8601 (`2026-10-06T05:00:00Z`). UI는 기기 현지 시각 표시.
- 초기 범위: KRX / KRW / 정수 주식 수량 / 지정가 모의주문.
- 금액은 JSON **정수 문자열** (`"72800"`). DB는 정수 또는 적합한 NUMERIC으로 저장.
- 4xx/5xx: 표준 HTTP 오류. 앱은 상세 응답이나 토큰을 로그에 남기지 않음.
- 페이지네이션·거래 이유·계획 관리·과거 봉·검증 성능 API는 후속 계약 범위.

## REST

| 메서드 | 경로 | 요청 / 응답 |
|---|---|---|
| POST | `/v1/auth/login` | `{email, password}` → `{access_token, user_id}` (`user_id`는 변하지 않는 문자열) |
| GET | `/v1/watchlist` | `{items: Quote[]}` |
| GET | `/v1/predictions/{symbol}` | `Prediction` 또는 `{status: "unavailable"}` |
| POST | `/v1/orders/check` | `OrderDraft` → `OrderCheck` |
| POST | `/v1/orders` | `OrderDraft + check_id`, `Idempotency-Key` 헤더 → `OrderReceipt` |
| GET | `/v1/orders` | `{items: OrderReceipt[]}`, 최신순 |
| POST | `/v1/ws-ticket` | `{ticket}`: 단기·일회용·사용자에 귀속된 WebSocket 티켓 |

```json
{
  "symbol": "005930", "name": "삼성전자", "price_won": "72800",
  "as_of": "2026-10-06T05:00:00Z", "sequence": 1234
}
```

Quote의 `sequence`는 **종목별로 지속적으로 증가**하며 재연결·서버 재시작에도 리셋하지 않습니다.
REST 스냅샷도 같은 순번 체계를 사용합니다. 과거/중복 WebSocket 이벤트는 무시합니다.
시세 `as_of`가 15초보다 오래되면 신규 주문을 막습니다. 15초는 구성 초기값이며,
장 마감·저유동성 종목의 정책과 heartbeat 기반 신선도 판단은 서버와 별도 합의해야 합니다.

```json
{
  "status": "available", "up": 0.62, "neutral": 0.24, "down": 0.14,
  "generated_at": "2026-10-06T05:00:00Z",
  "valid_until": "2026-10-06T05:05:00Z", "model_version": "baseline-v1"
}
```

Prediction의 예측 대상 기간은 초기 계약에서 다음 1시간으로 고정합니다.
`valid_until`은 **화면에 최신 예측으로 사용할 수 있는 기한**이며 예측 대상의 끝과 다릅니다.
확률 합은 1, 각 확률은 0~1. 최댓값 65% 미만이면 방향 판단 보류.

```json
{
  "symbol": "005930", "side": "buy", "quantity": 1,
  "limit_price_won": "72800", "order_type": "limit", "pilot_enabled": true
}
```

```json
{
  "check_id": "check-123", "allowed": true,
  "messages": ["급등 추격 가능성: 매매 계획을 확인하세요."],
  "expires_at": "2026-10-06T05:01:00Z"
}
```

`check_id`는 사용자·주문 내용·설정에 귀속되어야 합니다. 점검 후 가격·수량·ON/OFF를
수정하면 새로 점검합니다. `pilot_enabled=false`라도 서버의 잔액·보유량·한도·중복 검사는 유지합니다.

```json
{"order_id": "order-123", "symbol": "005930", "status": "accepted"}
```

상태: `accepted`, `partially_filled`, `filled`, `rejected`, `cancelled`.
접수 응답은 체결을 뜻하지 않습니다. 비즈니스 거절은 `status: rejected` 응답으로 표현합니다.

### 서버의 주문 원자성·멱등성 책임

1. 사용자 + Idempotency-Key에 고유 제약을 둡니다. 동일 키·동일 본문은 기존 결과 반환.
2. 동일 키의 기존 결과 조회는 점검 유효기간 검사 **이전**에 수행합니다. 응답 유실 후 재조회가 가능해야 합니다.
3. 같은 키에 다른 본문은 409로 거절합니다.
4. 신규 요청에만 점검 ID와 최신 잔액·보유량·시세·위험한도를 다시 검사합니다.
5. 필요한 행 잠금/적절한 격리 수준과 DB 트랜잭션 안에서 주문 기록과 자금 예약을 처리합니다.
6. 체결 시의 잔액·보유량 변경도 원자적으로 처리하고 중복 체결을 차단합니다.

클라이언트는 네트워크 오류 후 새 키를 만들지 않고 사용자의 재확인 동작에 동일 키와 본문을 사용합니다.
자동 재전송·오프라인 주문 큐는 없습니다. 실서버 모드에서는 전송 전에 사용자별 보안 저장소에
주문 본문·점검 결과·키를 기록하고, 응답을 받은 뒤 제거합니다. 앱 재시작 또는 재로그인 시 미확인
주문을 복원하며 새 주문 대신 사용자가 동일 키를 재확인할 수 있습니다. 다른 계정의 기록은 섞지 않습니다.
서버가 키를 너무 일찍 만료하면 중복 처리 위험이 있으므로 키 보관 기간과 장기 미확인 주문 처리 정책을
배포 전에 확정해야 합니다. 클라이언트의 재전송은 체결 확정이 아니라 기존 주문 결과 확인입니다.

## WebSocket

접속: `wss://<api-origin>/v1/ws?ticket=<single-use-ticket>`.
티켓은 서버에서 짧은 만료시간을 강제하고 로그에서 query를 마스킹합니다. 장기 토큰은 URL에 넣지 않습니다.
서버는 인증된 사용자의 관심종목만 구독하도록 권한을 검사합니다.

```json
{"type": "subscribe", "channel": "quotes"}
```

```json
{
  "type": "quote",
  "data": {
    "symbol": "005930", "name": "삼성전자", "price_won": "72800",
    "as_of": "2026-10-06T05:00:01Z", "sequence": 1235
  }
}
```

- 앱은 20초마다 `{"type":"ping"}`, 서버는 `{"type":"pong"}` 응답.
- 45초 이상 메시지가 없으면 다음 heartbeat 검사 시 연결을 종료하고 재연결.
- 지수 백오프 1~30초 + 0~499ms jitter, 재접속마다 새 티켓 발급·구독.
- 재연결 후 REST 스냅샷·예측·주문 내역을 새로 읽음.
- 앱 background에서는 연결 중단, foreground 복귀 후 재조회·재연결.
- 주문 전송은 REST로만 수행. 주문 체결 이벤트·예측 갱신 push는 후속 확장.

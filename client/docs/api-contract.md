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
- 이후 추가된 계획·피드백·데이터셋·백테스트·재생 계약은 이 문서 후반부와 각 기능 보고서를 기준으로 합니다.

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


## 2026-10-18 확장 API (구현 완료)

- `GET /v1/account`: 예수금·예약금·주문가능금액·평가금액·실현손익·보유종목. 금액은 정수 문자열; 시세/원가 미확인은 null.
- `GET/PUT /v1/settings`: order_limit_won, daily_loss_limit_won, cooldown_seconds, trading_rules. 한도는 정수, 쿨다운은 초. 일일 손실한도·쿨다운 자동 차단은 다음 단계.
- `GET/POST /v1/plans`: symbol, side, entry_condition, stop_loss_won(nullable), max_amount_won, split_order. 서버 id/created_at 추가, 사용자별 이력 보존.
- `GET /v1/symbols?q=...`: 등록 종목 검색, watched 상태.
- `PUT/DELETE /v1/watchlist/{symbol}`: 멱등 추가/삭제.
- `GET /v1/market/{symbol}/candles?interval=5m`: 1m/5m/15m/1h/1d, 최근 120개. OHLC 가격 문자열, volume 정수, opened_at/complete/source 포함. 응답에 status/as_of/stale.
- `GET /v1/fills`: 최근 200개 체결, order_id/side/quantity/price_won/fee_won/realized_pnl_won/source/quote_as_of/created_at.
- 주문 응답 status에 `filled` 추가. 접수 후 최신 시세의 지정가 조건 충족 시 worker가 체결. filled 주문 취소 요청은 filled를 그대로 반환.

모든 API는 기존 Bearer 인증과 계정별 격리를 사용합니다. 테스트 시세와 실제 증권사 데이터는 구분합니다.

## 단계 4~6 추가 계약 (2026-10-18)

- 주문 draft의 선택적 `plan_id`; 계획 `entry_min_won`/`entry_max_won` 구조화 가격 범위.
- 점검 응답 `analysis`에 behavior/risk/plan/prediction 스냅샷. Pilot Off는 행동 경고만 끄며 위험 규칙은 유지.
- 주문 접수 `warning_acknowledged`, `high_risk_acknowledged`, `trade_reason`. 주의 30점부터 이유 3자+확인, 60점부터 추가 확인. 서버에서 재평가하며 새 경고/점수 상승은 재점검 요구.
- `POST /v1/orders/check/{id}/dismiss`: 점검 보류 기록, 재사용 금지.
- `GET /v1/orders/{id}/analysis`: 본인 주문 당시 분석/확인/최종 차단 근거.
- `GET /v1/journal?days=30&offset=0`: 50개씩 주문 기록, 기간 집계·계획 준수·경고 결정·예측/실제 방향·피드백.
- 설정 `trading_paused`: 새 주문 중지. 미전송 설정 필드는 기존 값 보존.
- `GET /v1/predictions/{symbol}`: 모델 없음/합성/품질 미달/지연 시 unavailable; available이면 3방향 확률·지표·모델 기여·학습 검증 요약·버전·시점 포함.
- 미체결/취소/거절은 체결 성과에서 제외. 계획 미등록과 평가 불가도 준수율 분모 제외. 예측 중복 ID 및 판단 보류는 적중률 분모 제외.

## v3 시연 마무리 (2026-10-18)

- `POST /v1/auth/signup`: 이메일·12자 이상 비밀번호·동일한 확인 입력. 중복 이메일 409, 잘못된 입력 422. 생성 후 로그인하며 새 계정은 모의 현금 1,000만원/보유 없음.
- `PUT /v1/orders/{id}/note`: 본인 주문의 사후 복기 `text` (최대 2,000자). 최초 거래 이유·분석 스냅샷을 변경하지 않음.
- `GET /v1/system/status`: 인증된 사용자에게 시세 모드·모델 설정 유무·워커 설정·서버 주문 정지 상태. 비밀값/경로는 반환하지 않음.
- 웹소켓은 HTTPS → WSS, 명시적 로컬 디버그 HTTP → WS.
- 캔들 조회는 완성된 봉 및 단일 출처만 반환. 여러 출처를 하나의 차트에 섞지 않음.
- 마이그레이션 head: `20261018_release`.

## 전략·백테스트 확장

최신 스키마 `20261019_backtests`. 모든 경로는 로그인 사용자 소유 데이터만 접근합니다.

- `GET /v1/strategies` → `{items:[{id,name,symbol,fast_period,slow_period,enabled}]}`
- `POST /v1/strategies`, `PUT /v1/strategies/{id}` → 전략 설정 저장. 단기 2~100, 장기 3~200, 단기<장기. enabled는 시뮬레이션 허용이며 자동주문 상태가 아님.
- `POST /v1/strategies/{id}/backtests` → `{source,start,end,initial_cash_won,fee_bps,slippage_bps}`. 시간대 포함 ISO 시각, 5분봉, 시작 포함/종료 제외. 기본 자금 1천만원, 편도 2bp/5bp. 최대366일/2만봉. 201은 결과 보존 완료, 비활성409/데이터 부족422.
- `GET /v1/backtests?offset=0` → 요약20개와 next_offset(null이면 끝).
- `GET /v1/backtests/{id}` → 설정 스냅샷·원본해시·손익/낙폭/승률·trades·equity_curve.

결과는 수정되지 않으며 전략 PUT 이후에도 과거 설정을 유지합니다. 없는/타인 ID는404. 실제 주문 API 및 증권사 API를 호출하지 않습니다. 계산 정책은 루트 BACKTEST_REPORT.md 참조.

## 모의 자동매매 확장

스키마 `20261020_automation` 및 상세 정책은 루트 `AUTOMATION_REPORT.md` 참조.

- `GET /v1/automations`: 본인 실행 목록, 고정 전략 스냅샷, 예산, 상태, 마지막 평가 봉, 안내.
- `PUT /v1/strategies/{id}/automation`: `{enabled: true, budget_won: 500000}` 시작/재개. `{enabled: false}` 중지 및 해당 실행 미체결 취소. 이미 체결된 주식은 유지.
- `GET /v1/automations/{id}/events?offset=0`: 50개 신호 이력과 next_offset. order_status는 현재 체결/취소 상태.

모든 실행은 합성 시연 서버 전용입니다. 시작 시 보유/미체결·동일 종목 중복·주문한도를 검사합니다. 앱을 닫아도 서버 실행은 유지됩니다. 전략 PUT으로 enabled=false를 저장하면 자동 실행도 중지합니다. 원본 전략의 다른 필드 수정은 이미 시작된 실행 스냅샷에 적용하지 않습니다.

## CSV 연구 데이터

스키마 `20261021_datasets`. 상세 입력/검증/격리는 루트 `DATASET_REPORT.md` 참조.

`POST /v1/datasets/validate`, `POST /v1/datasets`에 `{name,symbol,provider,data_kind:"historical"|"synthetic",csv_text}` 입력. 검증만 수행하거나 전체 검증 후 개인 데이터 저장. 동일 사용자/종목/출처/종류/원본해시는 재사용합니다.
`GET /v1/datasets`는 메타데이터 목록, `DELETE /v1/datasets/{id}`는 본인 데이터 삭제. 최대3MB/20,000행/50개. 오류422, 한도409, 타인/없는 ID404.
백테스트 POST의 선택적 `dataset_id`는 공용 source보다 우선하며 소유권 및 전략 종목을 검사합니다. CSV는 공용 시세/모의 자동매매/AI모델에 자동 반영하지 않습니다.


## Feedback observation (v3 F-03/F-05, 2026-10-20)

- POST `/v1/orders/check/{id}/presented`: first rendered confirmation report, server timestamp, idempotent. Only owned, manual, allowed, unconsumed and unexpired checks can be marked initially. No proof of reading is inferred.
- POST `/v1/orders/check/{id}/dismiss`: explicit defer only; client back/barrier dismiss does not call this endpoint.
- GET `/v1/feedback?days=30&offset=0`: owned manual checks, 50 rows per page; groups, warning outcomes, denominators, timing, excluded legacy/automation counts.
- GET `/v1/feedback/export?days=30`: JSON `{filename,csv,rows,window,excluded,notes}`. UTF-8 CSV text, no names/email/reason/note free text. Time, symbols and record IDs remain.
- Accepted days: 1–365. More than 10,000 checks in window returns 422; narrow the window.
- OFF score is null in research data; it does not mean zero behavioral risk. ON/OFF is the order-warning toggle, not a randomized study arm.
- Timing is server presentation-report receipt to explicit decision receipt, not full transaction or cognitive latency. Missing/expired timing is not imputed.


## 과거 장세 재생 확장 (2026-10-20)

`/v1/replay` 하위 API는 기존 모의계좌와 별도입니다. [구현 계약 및 사용 방법](../../REPLAY_RESEARCH_REPORT.md)을 참조하세요. 쓰기 동작은 `request_id`와 `revision`을 요구하며 동일 키의 다른 본문·오래된 상태는 409입니다. 인증한 본인 사례/실험만 접근 가능합니다.

`POST /v1/replay/cases/{case_id}/runs`의 첫 실행은 `{request_id, pilot_enabled, plan?}`로 수동 시작하거나 `{request_id, randomize_order:true, plan?}`로 서버가 첫 Pilot 조건을 무작위 배정하게 할 수 있습니다. 두 선택은 함께 보낼 수 없습니다. 응답의 `allocation_method`, `condition_order`, `allocation_at`, `pair_id`, `sequence`를 저장하며 동일 요청 키 재시도는 기존 배정을 반환합니다. 완료 후 두 번째 실행은 `{request_id, pilot_enabled:<반대 조건>, paired_run_id:<첫 run id>}`로 시작합니다. 쌍 ID와 배정 순서를 이어받아야 합니다. 이 경로는 참가자 간 블록 균형 배정을 보장하지 않습니다.

### 재생 복기 업데이트 (2026-11-02)

- 완료된 run 응답의 `prediction_review`는 점검 당시 예측을 고유 모델/시각별로 집계하며, 실제 공개된 연속 12봉만 평가한다. `summary.warning_types`는 보존된 행동 규칙 평가의 유형별 결과다.
- `decisions`는 완료된 run에서만 점검 ID·가상 시각·결정·이유 목록을 반환한다. 진행 중에는 null이다.
- `defer` action의 기존 `reason`(최대 1000자)을 선택적으로 보존한다. `close`는 보류 이유를 기록하지 않는다. CSV reason은 보존 이유, JSON state.checks[].decision_reason은 원문이다.
- 새 run은 state에 행동 정책을 저장한다. 정책 없는 이전 run과 새 paired-run 연결, 조건이 달라진 paired-run, 두 번째/세 번째 중복 실행은 409다. 같은 요청 키의 재시도는 기존 실행을 반환한다.

### 일반 모의계좌 보류 이유 (2026-11-02)

`POST /v1/orders/check/{id}/dismiss`는 선택적 `{reason: string}`(최대1000자)을 받는다. 본문 없는 기존 요청도 지원한다. 응답 `{decision,reason}`. 동일한 이유 재요청은 기존 기록을 반환하며 다른 이유로 재작성은409. 이미 제출/소비된 점검 및 수동이 아닌 점검도409. 소유권 불일치는404. `GET /v1/feedback`에 `decision_reason`, `defer_reason_recorded`를 추가하며 일반 CSV에는 이유 본문을 제외하고 입력 여부만 제공한다. DB head `20261102_decision_reason` 적용 필요.

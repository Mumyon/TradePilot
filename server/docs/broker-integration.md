# 나중에 증권사 API를 붙일 위치

현재 연결된 증권사는 없습니다. 키·계좌·외부 주문 API 호출도 없습니다.

| 연결 대상 | 수정 위치 | 구현 내용 |
|---|---|---|
| 앱키·토큰 | `app/brokers/template.py::_access_token` | 서버 Secret 설정, 만료/재발급, 호출 제한 |
| 현재가 | `get_quote` | 응답을 `MarketQuote`로 정규화 |
| OHLCV | `get_candles` + `app/api.py::candles` | 봉 시각·완성 여부·페이지네이션 계약 |
| 계좌/잔고 | `get_balance` | 인증 사용자와 증권 계좌의 서버 측 매핑 |
| 주문 전송 | `place_order` | stable client_order_id, 접수/거절 구분, 응답 유실 재조회 |
| 주문 취소 | `cancel_order` | 증권사 취소 확인 후 내부 상태 반영 |
| 체결 수신 | `executions` | event_id 중복 제거, 부분 체결·재연결·복구 |
| 어댑터 선택 | `app/brokers/factory.py` | 새 구현체 선택, 주입 |
| 시세 스트림 저장 | `app/services/market.py::publish_quote` | UTC 기준 시각 유지, DB 순번 지속 증가 |

`contracts.py`의 `MarketDataPort`, `ExecutionPort`가 공통 경계입니다. 구체 증권사를 정하면
`template.py`를 참고하여 별도 구현 파일을 만들고 공급자 고유 필드·오류를 이 경계 안에서 변환합니다.
시세만 먼저 붙일 수 있으며, 시세 어댑터를 바꿔도 실계좌 주문이 자동 활성화되지 않습니다.

현재 snapshot 경로는 데모 확인을 위해 provider.get_quote를 호출합니다. 실제 공급자를 붙일 때는
사용자별 화면 조회마다 증권사 호출이 늘어나지 않도록 별도 수집 worker가 시세를 받아
`publish_quote`로 저장하고 REST/WS는 저장된 시세만 읽는 방식으로 옮기는 것이 좋습니다.
같거나 과거인 시각의 시세는 현재 저장 함수를 통해 갱신되지 않습니다. 같은 시각의 여러 틱이
중요한 공급자는 공급자 이벤트 ID/순번을 추가해 중복 및 역순 처리를 확장해야 합니다.

실계좌 주문을 연결할 때 `services/orders.py`의 DB 트랜잭션 안에서 외부 HTTP를 호출하지 마세요.
주문 의도/전송 대기 기록을 먼저 저장하고 별도 worker가 전송·결과 재조회를 맡도록 확장합니다.
증권사의 멱등성 지원 여부를 확인하고 결과 미확인 상태를 별도로 보존해야 합니다.
체결 이벤트는 event_id 고유 제약과 잔액·보유량·수수료 장부 트랜잭션을 구현한 뒤 반영합니다.

현재는 모의 접수 및 취소만 구현되어 있으며 이 파일은 연결 위치 안내입니다.
실주문 전송·체결·AI 모델·전략 엔진이 이미 동작하는 것으로 간주하지 않습니다.

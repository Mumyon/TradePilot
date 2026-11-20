# TradePilot Dart 파일별 수정 안내

앱에 들어가는 `client/lib`의 Dart 파일을 기능별로 정리했습니다. 파일명을 누르면 해당 코드를 열 수 있습니다.

## 화면과 화면 구성 요소

| 파일 | 해당 기능과 수정 위치 | 이전 파일 또는 위치 |
| --- | --- | --- |
| [login_screen.dart](../lib/app/login_screen.dart) | 로그인·회원가입 입력란, 배경 사진, 사진 정보 팝업, 로그인 후 확대 애니메이션 | `tradepilot_app.dart` 안의 `_Login` |
| [tradepilot_app.dart](../lib/app/tradepilot_app.dart) | 앱 공통 색상·글꼴, 로그인 세션 복원, 로그인/거래 화면 전환 | 동일 |
| [trading_home_screen.dart](../lib/features/trading/presentation/trading_home_screen.dart) | 하단 탭 이동, 종목 검색 및 차트 진입, 전일 대비 등락 표시, 매수·매도 주문 입력 팝업 | `trading_screen.dart` |
| [trading_layout_bindings.dart](../lib/features/trading/presentation/trading_layout_bindings.dart) | 관심종목과 차트 템플릿에 실제 데이터 연결. Pilot AI 카드의 판단·예측 상태 문구와 간격 수정 | `design_bindings.dart` |
| [stock_discovery_screen.dart](../lib/features/trading/presentation/stock_discovery_screen.dart) | 발견 탭의 정렬 버튼, 종목명, 현재가, 등락률, 거래대금 목록 | `trading_screen.dart` 안의 `_discoveryPanel` |
| [stock_price_chart.dart](../lib/features/trading/presentation/stock_price_chart.dart) | 차트 종류, 분봉 단위 메뉴, 거래량·MACD·RSI, 날짜 눈금, 현재가 표시, 발견 탭의 작은 캔들 | `market_chart.dart` |
| [chatgpt_analysis_panel.dart](../lib/features/trading/presentation/chatgpt_analysis_panel.dart) | ChatGPT 분석·복기의 본문, 결론 강조, 마크다운 표, 출처 더보기, 연결 안내 | `ai_replay_review.dart` |
| [order_confirmation_panel.dart](../lib/features/trading/presentation/order_confirmation_panel.dart) | ‘주문을 확인해 주세요’ 팝업의 주문 요약, 주문 전 ChatGPT 분석, 뒤로 가기·제출 버튼 | `pretrade_confirmation.dart` |
| [order_risk_check_dialog.dart](../lib/features/trading/presentation/order_risk_check_dialog.dart) | 데모와 과거 장세 실험에서 쓰는 주문 위험 점검 팝업 | `risk_confirmation.dart` |
| [stock_balance_screen.dart](../lib/features/trading/presentation/stock_balance_screen.dart) | 주식 잔고 탭의 순자산·평가손익, 보유 종목, 날짜별·종목별 매매손익 | 동일 |
| [paper_trading_management_screen.dart](../lib/features/trading/presentation/paper_trading_management_screen.dart) | 모의계좌 관리, 매매 계획, 주문·체결 내역, 과거 장세 실험 진입 | `workspace_screen.dart` |
| [trade_journal_screen.dart](../lib/features/trading/presentation/trade_journal_screen.dart) | 매매일지의 주문·체결 기록과 복기 메모 | `journal_screen.dart` |
| [pilot_feedback_history_screen.dart](../lib/features/trading/presentation/pilot_feedback_history_screen.dart) | Pilot 피드백 효과 기록, 점검 후 행동 이력, 연구용 CSV 복사 | `feedback_screen.dart` |
| [historical_market_replay_screen.dart](../lib/features/trading/presentation/historical_market_replay_screen.dart) | 과거 장세 재생, 모의 주문, AI 피드백 ON/OFF 실험 흐름 | `replay_screen.dart` |
| [strategy_backtest_screen.dart](../lib/features/trading/presentation/strategy_backtest_screen.dart) | 전략 생성·수정, 백테스트 실행과 결과 | `backtest_screen.dart` |
| [paper_automation_screen.dart](../lib/features/trading/presentation/paper_automation_screen.dart) | 모의 자동매매 시작·중지, 전략 신호와 주문 이력 | `automation_screen.dart` |
| [csv_dataset_screen.dart](../lib/features/trading/presentation/csv_dataset_screen.dart) | 백테스트용 CSV 파일 선택, 검증, 저장·삭제 | `dataset_screen.dart` |

Pilot AI의 간격은 `trading_layout_bindings.dart`의 `_pilotAiPredictionRowGap`, ‘예측 검증 모델 대기’ 문구는 `_pilotAiPredictionStatusText()`에서 수정합니다. 분석 답변의 표시 방식은 `chatgpt_analysis_panel.dart`에 있고, 답변에 사용할 기본 프롬프트는 서버의 [decision_ai.py](../../server/app/services/decision_ai.py)에 있습니다.

## 상태 관리와 데이터 연결

| 파일 | 해당 기능과 수정 위치 | 이전 파일 |
| --- | --- | --- |
| [main.dart](../lib/main.dart) | 앱 시작과 데모·서버 연결 선택 | 동일 |
| [app_config.dart](../lib/core/config/app_config.dart) | 데모 모드와 API 주소 읽기·검증 | 동일 |
| [trading_controller.dart](../lib/features/trading/presentation/trading_controller.dart) | 선택 종목, 시세·차트·예측 갱신, 주문 상태 관리 | 동일 |
| [trading_models.dart](../lib/features/trading/domain/trading_models.dart) | 시세, 예측, 주문 요청·점검·결과의 데이터 구조 | `models.dart` |
| [trading_repository.dart](../lib/features/trading/domain/trading_repository.dart) | 시세·예측·주문을 읽고 보내는 공통 인터페이스 | 동일 |
| [workspace_repository.dart](../lib/features/trading/domain/workspace_repository.dart) | 모의계좌·연구 등 부가 기능의 API 요청 인터페이스 | 동일 |
| [remote_trading_repository.dart](../lib/features/trading/data/remote_trading_repository.dart) | FastAPI 응답을 앱 시세·주문 데이터로 변환 | 동일 |
| [demo_trading_repository.dart](../lib/features/trading/data/demo_trading_repository.dart) | 서버 없이 실행할 때 쓰는 데모 시세·예측·주문 | 동일 |
| [api_client.dart](../lib/core/network/api_client.dart) | HTTP 요청, 로그인, 인증 헤더, 서버 오류 처리 | 동일 |
| [market_websocket.dart](../lib/core/network/market_websocket.dart) | 실시간 시세 연결, 인증 티켓, 연결 상태 확인과 재연결 | `market_socket.dart` |
| [token_store.dart](../lib/core/auth/token_store.dart) | 로그인 토큰 읽기·저장·삭제 | 동일 |
| [pending_order_store.dart](../lib/features/trading/domain/pending_order_store.dart) | 응답을 받지 못한 주문의 복구 정보와 저장 인터페이스 | 동일 |
| [secure_pending_order_store.dart](../lib/core/auth/secure_pending_order_store.dart) | 주문 복구 정보를 기기 보안 저장소에 계정별로 보관 | 동일 |
| [design_document.dart](../lib/core/design/design_document.dart) | [디자인 JSON](../assets/design/tradepilot.json) 읽기와 텍스트·도형·버튼 렌더링 | 동일 |

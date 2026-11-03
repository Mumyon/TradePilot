# ChatGPT Plus 종료 후 복기 · 2026-11-02

- 개인 로컬 공식 SIWC/Responses 연결 + 앱 계정별 OAuth CLI + 모델 선택. 실제 사용자 로그인/추론은 미완료, 유료 API 자동 전환 없음.
- ON/OFF 두 실험 완료 후 AI 복기 동의·큐·결과·캐시 UI. 익명 행동 집계만 외부 전송, 원시가격/종목/날짜/개인정보/이유 제외.
- ai_reviews 테이블, head `20261102_ai_reviews`. 시연 DB 마이그레이션 적용, 기존4테이블 행 식별자 해시 유지.
- 전체 서버215 + 추가 연결해제1(서로 다른216), Flutter전체49, analyze/Ruff/uv lock 정상. iPhone17 통합 통과(합성+HTTP응답 대역, 외부호출0).
- 일반서버18081 PID33088 ready, 일반앱 최신실행 후 detach. 임시18080 종료.
- 사용자는 `./tool/connect_chatgpt.sh` 실행 → 앱 계정 확인 → 공식 브라우저 Plus 로그인/동의/모델 선택 필요. 비밀번호·토큰을 채팅에 받지 말 것.
- [사용 안내](server/docs/chatgpt-review.md), [결과 보고서](CHATGPT_REVIEW_REPORT.md), `client/docs/ai-review/` 캡처/증거.

---

# AI 트리 모델 비교 · 2026-11-02

- HistGradientBoosting·CatBoost를 기존 softmax 2종 비교에 추가. 선택 extra model-comparison 및 uv 잠금 갱신·설치.
- 동일 실제 4,232봉/시간순 분할로 실행. 검증 선택은 balanced-softmax 유지. 두 트리 모두 Brier 비악화 및 65% 방향 판단 조건 미통과. 연결 후보 null, 앱 모델 변경 없음.
- schema2: 모든 후보 시험 성적·항목별 탈락 이유·코드/패키지 버전 보존. 검증 선택 고정, 시험으로 대체 후보 승격 금지.
- 실제 트리 포함 관련 테스트26 통과(건너뜀0), Ruff/포맷/uv lock 확인 통과. DB·모바일 전체 재검증은 미실시.
- [상세 결과](AI_TREE_COMPARISON_REPORT_2026-11-02.md). 다음: 추가 독립 데이터 확보 및 시간별 안정성 평가.

---

# AI 순차 개발 · 2026-11-02

실제 보존 4,232봉 해시 검증·전체 CSV 추출, 날짜별 결측/학습표본 품질 보고, 기본/클래스 균형 softmax 검증 선택 비교 구현. 신규4+회귀2 통과. 시험 F1 0.3421>기준0.2466이나 Brier 0.6691>0.5787, 보류100%로 연구 기준 미통과. 앱 모델 변경 없음. 신규 독립 데이터·실시간 어댑터·모델 운영 자동화 미완료. 상세 [AI 보고서](AI_DEVELOPMENT_REPORT_2026-11-02.md).

---

# 최신 개발 상태 · 일반 모의계좌 보류 이유 · 2026-11-02

- 남은 우선작업1 완료: 일반 계좌 주문 점검에서 선택적 보류 이유 저장→본인 피드백 펼치기 조회. 기존 재생 실험 기능 유지.
- 새 컬럼 order_checks.decision_reason, Alembic head **20261102_decision_reason**. 기존 시연 DB 마이그레이션 적용 및 서버18081 재시작. 이전 행 유지.
- 같은 이유 재요청 멱등, 다른 이유 재작성409, 제출/소비된 점검 또는 자동매매 점검 보류 금지. 기존 무본문 API 호환.
- 일반 CSV에는 자유서술문 제외, defer_reason_recorded만 추가. /v1/feedback 본인 조회에는 본문 제공.
- 관련 서버52개(회귀51+마이그레이션1), Flutter13개 통과. analyze/Ruff 정상. iPhone17 네이티브 연동 통과, `client/docs/manual-deferral-review/` 캡처/증거.
- 보고서: [일반 계좌 보류 이유](MANUAL_DEFERRAL_REPORT.md). 테스트18080 종료, 일반 시연 앱18081로 복원.
- 다음: 논문 실험 절차 및 지표·관찰 구간·순서 균형·제외 기준 준비. 실제 2020/2024 분봉 및 사람 대상 실험은 미완료.

---

# 최신 개발 재개 · 2026-11-02

- F-01 지난 iOS 실측 결과 확인: WebSocket 디코딩 후 이벤트 전달→Flutter 표시 20/20건, 평균37.182ms/p95 52.283ms/최대55.141ms, 누락0. 로컬 합성·debug 시뮬레이터 결과이며 외부망/AI 지연 제외.
- F-05 과거 장세 실험에서 보류 이유 선택 저장 및 종료 후 판단 기록 UI 추가. CSV/JSON 보존, 재시도 중복 없음, 빈 이유/창 닫기 구분. 일반 계좌 dismiss API는 이번 범위 아님.
- 관련 서버29/Flutter9 통과, Ruff/flutter analyze 정상. iPhone17 네이티브 통합(이유 입력→보류→복기→CSV) 성공. 일반 시연 서버18081 ready, 임시18080 서버 정리 완료. 일반 앱 재실행으로 복원.
- 상세: [2026-11-02 보고서](DEVELOPMENT_REPORT_2026-11-02.md).

---

# 최신 개발 상태 · F-05 재생 복기 및 연구 비교 보호 · 2026-11-01

- 사용자 요청: 기능명세서 기반으로 가능한 개발을 계속 진행. 제출본 PDF v3 10쪽 및 로컬 핵심 명세 대조.
- 재생 종료 후 당시 예측/1시간 후 실제 방향 복기 추가. 고유 모델·시각 중복 제외, 판단 보류 분모 제외, 조기 종료 미도달/12봉 결측 구분, CSV/JSON 포함.
- F-05 유형별 행동 피드백과 계획 미등록/평가 불가 체결 수 표시. OFF 내부 평가는 종료 전 비공개.
- 새 실행의 규칙 버전/정책 동결, 비교 키 포함, 변경된 규칙·모델·설정으로 paired-run 생성 거절. 한 쌍 최대 2실행 및 중복 재생 방지. 기존 짝 열기 UI.
- 이전 규칙 스냅샷 없는 기록은 열람/내보내기 유지, 새 쌍 연결은 거절. CSV 규칙 버전은 보존된 점검에서 읽음.
- 오프라인 `server/tool/replay_pair_summary.py`: 원본 JSON 중복/해시 검사, 동일조건 쌍 선별, 저장 상태 재집계, 참가자별 평균. 합성 기본 제외, 실제/합성 별도 집계, 기존 출력 덮어쓰기 거절.
- 검증: 서버 전체156 통과 + 쌍 집계 신규10 통과(서로 다른166개), Flutter46 통과, analyze/Ruff 정상. iPhone17 네이티브 통합 성공 및 캡처 저장. 실제 참여자 연구 아님.
- 상세: [2026-11-01 개발 보고서](DEVELOPMENT_REPORT_2026-11-01.md), `client/docs/replay-review-v2/`.
- Alembic head 유지 `20261023_replay`, 기존 시연 데이터 보존. 임시 테스트 서버18080은 검증 종료 후 정리할 것.
- 다음: F-01 시세 반영 시간 측정 보완, 실제 참여자 연구 준비. 2020/2024 실제 5분봉·증권사 키는 외부 의존으로 대기.

---

# 최신 개발 상태 · Pilot 조건 순서 무작위 배정 · 2026-11-01

- 과거 재생 연구 실험에서 첫 Pilot ON/OFF 조건을 서버가 무작위로 정하는 선택 기능을 추가했다. 수동 시작은 유지했다.
- 무작위 배정은 서버 RNG로 생성되며, 배정 방식·조건 순서·시각이 실행 JSON과 CSV/JSON 내보내기에 포함된다. 동일 요청 키 재시도는 같은 실행을 반환한다.
- 두 번째 paired-run은 반대 조건을 사용하고 동일 순서·쌍 ID를 이어받는다. 앱의 실행 화면에 현재 순서와 배정 방식을 표시한다.
- 연구상 한계: 이는 실험 쌍 안의 순서를 무작위화하는 기능이며 참가자 사이의 균형 배정(블록 무작위화)은 제공하지 않는다. 실제 모집 전 지도교수와 배정 절차를 확정할 것.
- 검증: 서버 전체 140개 통과, Flutter 전체 테스트 45개 통과, `flutter analyze` 정상, Ruff 통과. 실제 사람 대상 연구나 통계적 효과는 검증하지 않았다.
- 상세: [재생 연구 보고서](REPLAY_RESEARCH_REPORT.md).

## 최신 재개 메모 · 실제 과거 5분봉 · 2026-10-20

- 사용자 선택: 일봉 대체 없이 5분봉 유지. 이후 Yahoo Finance 국내 실제 5분 OHLCV 확보·기본 연결 완료. 원래 유명한 2020/2024 사건 데이터는 아님.
- 고정 파일 `server/app/data/historical/2026-10-20/`: 원 응답 gzip 2개, 실제 사례 JSON/CSV 4개, 사례 이전 자료로 학습한 모델 JSON 3개, SHA-256 manifest. 일봉은 교차 대조 전용. 원본 null/장 후반 누락을 보간하지 않음.
- 신규 `historical_data.py`, offline `tool/build_historical_catalog.py`, POST `/v1/replay/historical`. 앱 모의투자 진입 시 사용자별 중복 없이 등록. 이전 합성 사례/실험 보존. 사건 설명은 확보 대기로 접음.
- 재생 gap이면 미체결 취소·감사 기록. 차트도 장간/결측 선을 끊음. 시간 KST 표시. 일봉 대조의 미래 OHLCV는 종료 전 API에서 제외. 자료 끝까지 1시간 미만이면 AI 보류.
- 실제 모델: 7/29 학습 표본 부족, 8/21 기준 미달, 10/13·10/15 기존 기준 통과. 통과 모델도 최종 검증에서 모두 보합으로 분류, F1 기준선 동일, 보류율 높음. 예측력이 좋다는 결론 금지.
- 서버 전체135+추가1(신규 실제 데이터10 모두 통과), Flutter44 및 수정 화면3 재검증. 네이티브 통합 스크립트 `historical_replay_test.dart`, 캡처 `client/docs/historical-review/`. 자동 검증 자료를 참여자 연구 자료로 사용하지 말 것.
- 기존 데이터베이스 마이그레이션 head `20261023_replay` 유지; 이번 스키마 변경 없음. 기존 시연 DB 보존, 18081 서버 최신 코드로 재시작. 재개 시 PID를 가정하지 말고 포트/health 확인.
- 최종 실행: 시연 서버18081 ready, iPhone17 최신 일반 앱 빌드·실행 후 detach 완료. 임시 검증 서버18080 종료. 데이터·사진·보고서 저장 완료.
- 교수님 검토용 보고서(대본 아님): [TRADEPILOT_PROJECT_REPORT.md](TRADEPILOT_PROJECT_REPORT.md). iPhone17 직접 캡처 4장, Mermaid 시스템 구조, 연구 질문·설계 및 한계 수록.
- [상세 보고서](HISTORICAL_DATA_REPORT.md). 아래 항목은 이전 단계 기록.

> 최신 변경(2026-10-20): [실제 과거 5분봉 적용 보고서](HISTORICAL_DATA_REPORT.md). 삼성전자 2026-07-29·08-21·10-13·10-15의 Yahoo Finance 실제 OHLCV를 모의투자 기본 사례로 연결했습니다. 2020/2024 사건의 실제 5분봉은 여전히 확보 대기입니다. 아래의 “합성 사례만 있음” 설명은 이전 시점 기록입니다.

> 최신 작업(2026-10-20): [로컬 AI·과거 장세 모의실험](REPLAY_RESEARCH_REPORT.md). 앱 내 사례 학습 및 독립 계좌 재생, 동일인 ON/OFF 쌍 비교, CSV/JSON 연구 기록 추가. 사용자 확인: 실제 데이터 없음, CSV 등록+합성 연습으로 준비.

> 최신 작업(2026-10-20): [행동 점검·피드백 연구 기록](FEEDBACK_RESEARCH_REPORT.md). 아래 과거 단계의 미구현/환경 설명은 해당 시점 기록입니다.

# TradePilot 작업 재개 기록

## 최신 상태 · 과거 장세 재생 및 AI 연구 모드 · 2026-10-20

- 사용자가 요청한 비용 최소 AI는 기존 순수 Python 다중분류 로지스틱 회귀를 재사용, 앱에서 사례별 학습·검증·추론까지 연결. 실제 CSV는 아직 없음(사용자 확인), 합성 급등/급락 사례로 시연 가능.
- 하단 모의투자 탭 → 독립 계좌·가상 시계의 연구 실험 화면. 기존 대시보드/전략은 `기존 모의계좌 · 전략`으로 접근. DEMO_MODE=false 필요.
- 원 CSV 불변 사례 스냅샷, 학습 구간은 재생 시작 이전, 미공개 봉 추론 차단, next-open 지정가 체결/수수료/예약, 같은 사례·계획·설정 ON/OFF 쌍, 경고 노출·보류·판단 시간·준수율, 종료 후 CSV+전체 OHLCV/모델 JSON 내보내기. AI는 두 조건 모두 제공하고 행동 피드백만 조작.
- 공통 `risk.assess`로 기존 실시간 규칙과 재생 규칙 공유. OFF 내부 평가값은 종료 전 비공개. 실제 연구 효과/정확도를 입증한 상태가 아님.
- Alembic head `20261023_replay`, 기존 시연 DB `server/.demo/postgres`에 적용. 최종 로컬 서버 18081 정상 실행. 최신 iPhone17 시연 앱 실행 후 detach 완료. 테스트 전용 18080 서버 종료. 기존 .env DB 변경 없음.
- 서버 전체126, Flutter전체44, Ruff/analyze/diff-check 정상. iPhone17 실제 API 통합 통과, 캡처/기계 검증 기록 `client/docs/replay-review/`.
- 상세 사용법·연구 설계 범위·재현 한계·화면: [REPLAY_RESEARCH_REPORT.md](REPLAY_RESEARCH_REPORT.md).

이하 문단은 이전 단계별 기록입니다.


## 최신 상태 · CSV 연구 데이터 · 2026-10-19

앱 파일 선택 → 검증 → 개인 데이터 저장/삭제 → 백테스트 데이터 선택 및 기간 자동 입력 구현.
업로드는 별도 datasets 테이블, 공용 캔들/자동매매/AI 모델 불변. 3MB/2만행/사용자50개, 행 검증/중복 재사용/소유권 검사.
서버108개/Flutter37개 전체 통과, analyze 정상. iPhone17 실제 서버 통합 통과 (파일 선택 결과 주입). 최신 검증 결과는 [CSV 보고서](DATASET_REPORT.md).
최신 head `20261021_datasets`. 별도 시연 DB에 적용했고 서버18081 실행 중, 임시 서버18080 종료. 기존 .env 개발 DB 불변. Android ARM64 debug 빌드 성공. 최신 iPhone17 시연 앱 실행 후 detach 완료. 합성 예제 server/examples/synthetic_5m.csv. 실제 데이터 및 앱 내 AI 학습은 아직 없음.
이하 이전 챕터별 기록입니다.

## 최신 상태 · 모의 자동매매 확장 · 2026-10-19

저장 전략 → 완료 5분봉 신호 → 기존 위험 점검 → 모의 접수/체결 → 신호 이력 구현.
시연 서버 전용, 명시적 시작/중지, 고정 전략/예산, 동시 워커 중복 방지, 행동 경고 자동 승인 없음.
중지는 미체결 취소/예약금 해제, 보유 유지. 수동 거래 감지/거래 정지 시 자동 중지.
서버95개, Flutter34개 통과. iPhone 실제 서버 통합 통과. 상세 [자동매매 보고서](AUTOMATION_REPORT.md).
최신 head `20261020_automation`. 별도 시연 DB에 적용, 서버18081 실행 중. 임시 통합 서버18080 종료. 최신 iPhone17 시연 앱 실행 후 detach 완료. Android ARM64 debug 빌드 성공. 실제 투자/증권사 연결 아님. 실제 CSV 및 AI/RSI 복합 전략은 아직 후속.
아래는 이전 챕터별 기록입니다.

## 최신 상태 · 전략 관리·백테스트 확장

사용자가 후속 챕터로 전략 관리·백테스트를 선택. 5분봉 SMA 전략 저장/수정/활성, 다음 봉 시가 체결 백테스트, 수수료·슬리피지·낙폭·거래 내역·사용자별 불변 결과 저장 구현.
서버83개/Flutter33개 통과, analyze 정상, iPhone17 실제 API 통합 통과. 상세 [백테스트 보고서](BACKTEST_REPORT.md).
최신 Alembic head `20261019_backtests`. 별도 로컬 시연 DB에 적용하고 서버18081 재시작. 기존 .env 개발 DB 변경 없음. Android ARM64 debug 빌드 성공. 최신 시연 앱을 iPhone17에서 실행 후 detach했으며 서버18081은 실행 중. 임시 통합 서버18080은 종료함.
진입: 모의투자 → 백테스트. 실제 CSV 없음, 기본 demo는 합성 데이터. AI/RSI 복합 전략·자동매매 미구현.
이하 v3 보고서는 확장 전 기록입니다.

## 최신 상태 · v3 핵심 구현 및 시연 준비 · 2026-10-18

사용자가 ‘끝까지’ 범위를 **v3 핵심 기능 완성 및 시연 준비**로 선택. 자동매매/백테스트는 후속 확장.
회원가입, 복기 메모, 동적 관심종목, 실제 계좌/일지 화면, 간결한 확인, AI 갱신/만료, HTTP/WS 로컬 연결 수정 완료.
서버 77개, Flutter 32개 통과. iPhone17 네이티브 통합 통과, Android ARM64 debug APK 빌드 성공.
행동 16개 라벨 시나리오 및 주문 120건 검증. 실데이터 AI 학습/사용자10명 평가는 아직 대기.
[최종 보고서](V3_COMPLETION_REPORT.md) / [시연 실행](DEMO_GUIDE.md).
최신 Alembic head `20261018_release`. 기존 개발 DB는 변경하지 않았음.
별도 로컬 시연 DB `server/.demo/postgres`, 서버 127.0.0.1:18081. `tool/start_demo_server.sh`, `tool/start_ios_demo.sh` 사용.
실행 중인 시연 서버가 있으면 재시작하지 말고 health/ready 확인. 테스트 서버18080은 종료함. iPhone17에 시연 앱 로그인 화면을 실행해 둠. 서버 PID는 고정값이 아니므로 재개 시 health 확인.
아래 기록은 단계별 과거 상태임.


## 최신 개발 · 4~6단계 · 2026-10-18

행동 경고/위험 차단, CSV 학습·검증 경로, 매매일지/피드백 구현 및 재검증 완료.
서버 55개·Flutter 27개 통과, iPhone 17 실제 서버 통합 검증 통과.
실제 학습 데이터 없음: 사용자 선택은 CSV 준비. 실데이터 모델 성능 및 증권사 연동은 미완료.
상세: [4~6단계 보고서](STAGES_4_6_REPORT.md), [CSV 안내](server/docs/csv-training.md).
기존 개발 DB 변경 없음: 실행 전 alembic upgrade head (`20261018_journal`) 필요.
아래는 이전 단계 시점 기록으로, 행동 경고/위험 규칙 미연결 문구는 현재 상태가 아닙니다.


## 최신 개발 · 1~3단계 · 2026-10-18

계좌/설정/관심종목/계획 저장, 서버 캔들 차트, 모의 체결/손익 처리를 추가했습니다.
상세 범위·정책·검증·실행 방법: [개발 결과 보고서](DEVELOPMENT_REPORT_2026-10-18.md).
증권사/AI/행동 분석은 미연결이며, 일일 손실한도·쿨다운은 저장만 지원합니다.
새 기능은 앱 DEMO_MODE=false + 서버 MARKET_DATA_MODE=demo에서 확인합니다.
개발 DB는 건드리지 않았으므로 서버 배포/실행 전 Alembic head 적용이 필요합니다.
이하 내용은 이전 시점의 기록입니다.


## 최신 완료 상태 · 원본 JSON 디자인 적용 · 2026-10-08

- 디자인 작업 재개 후 구현 및 검증 완료. 상세 내용: [client/docs/design-implementation.md](client/docs/design-implementation.md).
- 원본 design.json의 35개 화면/상태·색상·좌표·SVG·폰트를 활용한 네이티브 Flutter 화면으로 교체. 원본 자료 변경 없음.
- 하단 5개탭, 실제 검색, 수량/가격 편집, 서버 점검→확인→접수, 주문 복구·로그아웃·일지를 연결함.
- iOS Apple SD Gothic Neo 400/500/600 폰트 폭 일치 확인. Android는 Noto Sans KR 대체. 상태표시줄/안전영역은 기기 기준.
- 정적 분석 오류/경고 없음, Dart 포맷 및 git diff --check 통과.
- Flutter 테스트 20개 통과. iPhone17 통합 테스트 통과, 원본 35개 + 앱 9개 화면 캡처 및 비교. Android ARM64 APK 빌드 성공.
- 디자인 비교: client/docs/design-review/compare-watchlist.png 및 contact-1~5.png.
- 임시 SDK가 삭제되어 `.tools/flutter`와 `.tools/pub-cache`에 복구. `client/tool/flutterw`로 실행. .tools는 Git 제외.
- 현재 로컬 서버와 이전 trycloudflare 주소 응답 없음 확인. 디자인 확인용 iOS 앱은 DEMO_MODE=true로 실행. 서버 재연결은 RUN_TEST_GUIDE.md 참고.
- 이 작업은 서버 API·증권사 연동·자동매매 엔진 구현을 변경하지 않음. API가 없는 성과/계좌/AI는 서버 모드에서 대기 표시.
- 이전 중단 기록은 아래 및 DESIGN_HANDOFF.md에 보존. 더 이상 '새 화면 미연결' 상태가 아님.

---

## 최우선 재개 지점 · 디자인 일치 작업 중단 저장 · 2026-10-08

사용자가 크레딧 초기화 후 이어서 작업하도록 현재 과정 저장 요청. **[DESIGN_HANDOFF.md](DESIGN_HANDOFF.md)를 먼저 읽을 것.**

- 요청: UI_figma/output/TradePilot-Figma-UI/design.json 기준 구성·디자인·폰트 정확히 일치.
- 35개 화면, 5개탭, Apple SD Gothic Neo, 원본 색/좌표/SVG 분석 완료.
- JSON asset, 네이티브 디자인 렌더러 및 데이터 바인딩 초안, flutter_svg, Android용 Noto 폰트 저장.
- **화면 호스트 연결/테마 수정/시각검증/분석·테스트 미완료. 앱은 아직 기존 화면.**
- 다음: TradingScreen 새 디자인 연결, 기존 서버 주문·복구 로직 유지, iOS 화면 비교 및 테스트.
- 현재 Docker 서버·DB 실행 확인됨. server/.env의 MARKET_DATA_MODE=demo 적용 완료. 계정1개/관심종목2개.
- 사용자 iPhone17 시뮬레이터 빌드·실행 성공 확인. 아래 Docker 없음/iOS미검증 기록은 과거 상태.

---

## 최신 상태 · 2026-10-08

사용자 요청: FastAPI 서버 생성, 증권사 API는 나중에 붙일 수 있는 연결 지점만 마련.

- `server/`에 FastAPI + SQLAlchemy + psycopg + PostgreSQL + Alembic 구현.
- 클라이언트 계약의 로그인·관심종목·AI 미연결 응답·주문 점검/접수·주문 내역·WebSocket 티켓/스트림 제공.
- 서버 로그아웃 및 모의주문 취소 API 추가. 클라이언트 UI에 추가 API 연결은 별도 후속 작업.
- 비밀번호 Argon2, 서버 세션·티켓 해시 저장, 계정별 조회 권한.
- 모의주문은 사용자 행 잠금 + DB 트랜잭션으로 금액/수량 예약. 실제 체결/실주문 없음.
- 증권사 어댑터 인터페이스: `server/app/brokers/contracts.py`, 구현 자리: `template.py`, 선택 위치: `factory.py`.
- 기본 MARKET_DATA_MODE=disabled. 명시적 demo 모드만 가상 시세. AI는 unavailable.
- 실제 임시 PostgreSQL 기반 통합 테스트 16개 통과. Ruff 검사·포맷 통과.
  DB 확정 후에만 응답을 전송하며, 확정 실패 시 주문·예약 롤백을 검증했다.
- Docker/Compose 파일과 lockfile 준비. 이 Mac에는 Docker가 없어 컨테이너 빌드는 미검증.
- `.env` 및 실제 사용자 비밀번호는 생성하지 않았고 지속 실행 중인 서버/DB도 없음.
- 실행/연결: `server/README.md`, `server/docs/broker-integration.md`.
- 다음 단계: 사용자 환경 PostgreSQL 설정, 계정 CLI 생성, TLS 설정 후 Flutter 실기기와 REST/WSS 재검증.

검증 환경: `server/.venv` (Python 3.12.14), uv.lock으로 의존성 고정.
테스트는 `pgserver` 임시 DB 또는 TEST_DATABASE_URL의 무작위 전용 스키마를 사용하고 종료 후 정리.

```sh
cd /Users/mumyon/Documents/TradePilot/server
uv sync --frozen --group postgres-test --python 3.12
uv run --group postgres-test pytest -q
uv run ruff check .
```

---

## 이전 클라이언트 구성 기록 · 2026-10-06

갱신: 2026-10-06. 사용자가 상태 저장을 요청한 뒤 바로 `계속해줘`로 작업 재개를 요청함.

## 요청과 범위

Flutter + Dart로 Android·iOS 클라이언트를 구성. WebSocket 사용, 서버 FastAPI, DB PostgreSQL 전제.
구성 완료 후 사용자에게 재검증 방식 질문, Mermaid 구조도 출력.
실제 서버·DB 구현과 완성된 전체 앱 개발은 이번 구성 단계에 포함하지 않음.
기존 `UI_figma/` 자료는 변경하지 않음. 프로젝트는 Git 저장소가 아님.

## 완료

- `client/`: Flutter 클라이언트 소스, 공식 생성 Android/iOS 호스트 프로젝트, pubspec.lock.
- 관심종목·종목/AI·주문 팝업·매매일지·설정의 다크 테마 기본 UI.
- ChangeNotifier Controller → Repository → REST / WebSocket 계층과 데모/실서버 모드.
- HTTPS REST, WSS 티켓 접속, 재연결·heartbeat·수명주기 관리.
- 서버 위험검사 후 최종 주문, 동일 키 재확인, 계정별 보안 저장소의 미확인 주문 복원.
- 390×844 모바일 주문 흐름을 포함한 `flutter test` **13개 통과**.
- `dart analyze`: 문제 없음. `dart format --output=none --set-exit-if-changed lib test`: 통과.
- Android ARM64 디버그 APK 빌드 성공: `client/build/app/outputs/flutter-apk/app-debug.apk`.
  빌드 도구가 NDK 28.2.13676358, Android SDK Platform 35/36, CMake 3.22.1을 준비한 뒤 성공했다.
- README 및 `client/docs/api-contract.md`, `architecture.mmd`, `verification.md` 작성.

## 남은 마무리

1. Android 빌드 세션 `98069`는 exit code 0으로 종료됐다. 빌드 결과를 검증 문서에 반영했다.
2. 클라이언트 구성 단계는 완료. 다음 단계는 사용자가 선택한 방식으로 재검증 진행.
3. 최종 답변에서 구성 위치·13개 테스트/분석 결과·한계 및 Mermaid 구조도를 제공한다.
4. 사용자 재검증 질문을 유지. 이미 비동기 질문을 보냈으나 선택 답변은 아직 받지 못함:
   Android 데모 화면 / FastAPI REST·WS 실서버 / 구조도·API 계약 검토 중 선택.

## 실행 환경

- 프로젝트: `/Users/mumyon/Documents/TradePilot/client`
- 임시 Flutter SDK: `/tmp/tradepilot-flutter-sdk` (3.47.6, Dart 3.13.5)
- PUB_CACHE: `/tmp/tradepilot-pub-cache`
- GRADLE_USER_HOME: `/tmp/tradepilot-gradle`
- Android SDK: `/Users/mumyon/Library/Android/sdk`
- Java: Android Studio에 포함된 JBR 25
- 전체 Xcode 없음 (`xcode-select -p`는 CommandLineTools). iOS 빌드·실기기 검증 미실행.
- 임시 폴더는 정리될 수 있으므로 다음 세션에서 존재 여부부터 확인.

```sh
cd /Users/mumyon/Documents/TradePilot/client
PUB_CACHE=/tmp/tradepilot-pub-cache /tmp/tradepilot-flutter-sdk/bin/flutter --no-version-check test --no-pub
/tmp/tradepilot-flutter-sdk/bin/cache/dart-sdk/bin/dart analyze
PUB_CACHE=/tmp/tradepilot-pub-cache GRADLE_USER_HOME=/tmp/tradepilot-gradle /tmp/tradepilot-flutter-sdk/bin/flutter --no-version-check build apk --debug --target-platform android-arm64
```

샌드박스 밖 도구 초기화·패키지 다운로드·로컬 socket 테스트를 위해 exec escalation을 사용했다.
SDK 최초 `flutter --version`이 전체 Git 태그를 받으려 해 해당 fetch만 중단했고,
그 뒤부터 `--no-version-check`를 사용한다. 테스트·분석에 지장 없음.

## 설계 및 알려진 한계

- 기본은 데모(가상 시세, 예시 AI, 1~10주 검사, 접수 예시). 실제 체결 엔진 없음.
- 실서버는 `DEMO_MODE=false`, `API_BASE_URL=https://...` (경로 없는 origin).
- FastAPI 계약은 아직 합의되지 않은 초안. 로그인 응답에 `access_token`, `user_id` 문자열 필요.
- PostgreSQL은 FastAPI에서만 접근. DB 정보나 증권사 비밀키는 앱에 두지 않음.
- 미확인 주문 키는 실서버 모드에서 계정별 secure storage 저장, 데모는 메모리.
- 시세 sequence는 종목별 지속 증가, 15초보다 오래된 시세는 새 주문 차단.
- TradePilot OFF여도 필수 위험검사는 유지한다는 제안 설계.
- 캔들 차트·전체 종목 검색·상세 거래 이유/계획/피드백은 연결 전인 영역으로 명확히 표시.
- 인증 토큰 refresh 및 만료 시 자동 로그인 화면 전환은 후속 범위. 설정에서 재로그인 가능.
- 서버 통합 및 실제 기기의 보안 저장소·계정 전환·주문 복원 검증 필요.
- iOS/Android 번들 ID·서명은 템플릿 초기값. 앱스토어 배포 준비 완료라고 보고하지 말 것.


## 2026-10-20 · F-03/F-05 피드백 연구 기록

- 공포매도 안내에 평가손익·손절 조건 추가, 기존 4유형/가중치·계획 예외·OFF 위험 규칙 유지.
- 수동 점검의 최초 화면 표시·명시적 보류/제출 시각·실제 주문 ID 보존. 단순 창 닫기는 보류로 집계하지 않음.
- 매매일지 상세에서 피드백 기록 화면 연결: 유형별 보류/거절/취소/체결, 같은 계정 ON/OFF 계획 준수·확인 시간·CSV 복사.
- 자동매매 및 도입 전 기록은 연구 비교에서 제외. OFF 점수를 0으로 간주하지 않음.
- 새 Alembic head `20261022_feedback`. 서버117개, Flutter41개, analyze/Ruff/공백 검사, iPhone 실제 API 통합 검증 통과.
- 실제 AI 모델·사용자 연구 결과는 여전히 없음. 명세 기준과 분모·사용법은 `FEEDBACK_RESEARCH_REPORT.md` 참조.

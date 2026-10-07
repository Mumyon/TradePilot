# TradePilot 작업 재개 기록

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

# TradePilot Flutter 클라이언트

Android·iOS용 **초기 클라이언트 구성**입니다. 서버·DB 구현은 포함하지 않습니다.
`UI_figma`의 다크 테마·탭·주문 팝업을 참고했으며 전체 디자인의 완성 구현은 아닙니다.

## 실행

Flutter stable SDK와 각 플랫폼 개발 도구가 필요합니다. 생성된 플랫폼 코드는 `android/`, `ios/`에 있습니다.
구성 검증에는 Flutter 3.47.6 / Dart 3.13.5를 사용했습니다. 모든 명령은 `client/`에서 실행합니다.

```sh
flutter pub get
flutter run --dart-define=DEMO_MODE=true
```

이 작업에서는 시스템 PATH를 변경하지 않고 SDK를 `/tmp/tradepilot-flutter-sdk`, 패키지 캐시를
`/tmp/tradepilot-pub-cache`에 준비했습니다. 현재 환경에서 바로 실행하려면 아래 명령을 사용할 수 있습니다.
임시 폴더는 정리될 수 있으므로 지속 개발 시 Flutter SDK를 영구 개발 경로에 설치하세요.

```sh
PUB_CACHE=/tmp/tradepilot-pub-cache /tmp/tradepilot-flutter-sdk/bin/flutter --no-version-check run --dart-define=DEMO_MODE=true
```

기본은 데모입니다. 가상 시세가 2초마다 바뀌며 주문은 **접수 예시**만 생성합니다.
AI 확률·위험 점검 역시 테스트 데이터이고 실제 투자 분석·가상 자금 회계·매칭 엔진은 없습니다.

```sh
flutter run --dart-define=DEMO_MODE=false --dart-define=API_BASE_URL=https://api.example.com
```

실서버 모드는 [API 계약](docs/api-contract.md)을 구현한 서버가 있어야 합니다.
HTTPS/WSS를 사용하고 인증서 검증을 해제하지 않습니다. 로컬 개발도 신뢰할 수 있는 HTTPS 환경을 준비하세요.
앱에 DB 비밀번호·증권사 API 비밀키를 넣지 않습니다.

## 구성

```text
lib/
  main.dart                        # 구성 읽기, 의존성 주입
  app/tradepilot_app.dart           # 테마, 로그인, 세션 복원
  core/
    config/app_config.dart         # 데모/서버 환경 분리
    auth/token_store.dart          # 플랫폼 보안 토큰 저장
    auth/secure_pending_order_store.dart # 계정별 미확인 주문 보존
    network/api_client.dart        # 인증 REST, timeout, 명시적 주문 키
    network/market_socket.dart     # 티켓 인증, heartbeat, 재연결
  features/trading/
    domain/                        # 모델, 저장소 인터페이스
    data/                          # 데모 / FastAPI 저장소
    presentation/                  # ChangeNotifier 상태, 화면/주문 UI
test/                              # 주문 상태, API, WS, 위젯 검증
docs/
  api-contract.md                  # 제안 REST/WS 계약과 서버 책임
  architecture.mmd                 # Mermaid 구조도
  verification.md                  # 검증 결과와 수동 재검증
```

작은 초기 앱이므로 하나의 trading 기능 모듈로 시작합니다. 기능이 커지면 market/prediction/order/journal로
분리하되 UI → Controller → Repository → API/Socket 의존 방향을 유지합니다.
추가 상태관리 프레임워크 없이 Flutter 기본 ChangeNotifier/ListenableBuilder를 사용합니다.
코드 생성 도구 없이 DTO를 파싱하므로 서버 명세 변경 시 모델 및 계약 테스트를 함께 수정해야 합니다.

## 현재 포함

- 관심종목 내 검색, 종목 선택, 시세 기준 시각·신선도 표시.
- AI 3방향 확률·판단 보류·만료 표시.
- 지정가 입력, TradePilot ON/OFF, 필수 점검, 최종 확인, 접수/체결 상태 구분.
- 응답 유실 시 동일 주문 키 재확인, 실서버 모드의 계정별 미확인 주문 복원, 이중 클릭 차단, stale/offline 신규 주문 차단.
- 로그인과 토큰 보안 저장, 401 세션 삭제, 설정에서 재로그인.
- foreground/background WebSocket 수명 관리, 재연결과 REST 재동기화.

## 후속 구현 범위

- OHLCV 캔들 차트, 전체 종목 검색·관심종목 편집.
- 사용자 매매 계획·위험한도 저장, 주문 이유·유형별 점수·상세 매매일지.
- 계정 등록·비밀번호 재설정·refresh token·토큰 만료 시 자동 로그인 화면 전환.
- 미확인 주문의 장기 보관·키 만료 정책과 서버 통합 검증.
- 체결/예측 push 이벤트, 서버 점검·시장 시간별 신선도 정책.
- 실계좌·자동매매는 초기 범위 밖. 원본 디자인의 자동매매 탭은 현재 구성에서 제외.
- 한국어 폰트·접근성·실기기 키보드·네이티브 보안 저장소 검증.

## 검증 명령

```sh
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build apk --debug
flutter build ios --simulator
```

iOS 빌드는 전체 Xcode 및 플랫폼 의존성 도구가 필요합니다. 배포용 applicationId/bundle ID,
서명, 앱 아이콘, 스토어 메타데이터는 확정하지 않은 초기값입니다.

설계 참고: [Flutter 아키텍처 권장사항](https://docs.flutter.dev/app-architecture/recommendations),
[Flutter WebSocket 가이드](https://docs.flutter.dev/cookbook/networking/web-sockets).

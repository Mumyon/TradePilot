# 원본 JSON 디자인 적용 기록

2026-10-08. 기준: `UI_figma/output/TradePilot-Figma-UI/design.json` 및 같은 폴더의 SVG·PNG. 원본 파일은 변경하지 않았습니다.

## 적용한 내용

- 원본 JSON을 `assets/design/tradepilot.json`에 동일하게 보관합니다. 테스트에서 원본과 byte 단위로 동일함을 확인합니다.
- 원본의 35개 화면/상태를 렌더링합니다. 관심종목·차트·자동매매·매매일지·전체 메뉴의 5개 탭, 검색 팝업, 매수/매도 상세·최종확인·완료 구성을 연결했습니다.
- 6개 색상, 각진 패널·버튼, 좌표·간격·글자 크기와 굵기, 구분선, 188개 SVG 노드의 원본 경로와 viewport를 사용합니다. 화면 PNG를 앱 배경으로 사용하지 않습니다.
- iOS: Apple SD Gothic Neo 400/500/600. UIKit과 Flutter TextPainter의 `TradePilot` 27pt 폭을 비교해 Regular 115.749pt, Medium 114.453pt, SemiBold 118.341pt 일치를 확인했습니다.
- Android: 원본 생성기의 대체 후보인 Noto Sans KR을 번들로 제공합니다. Apple 전용 폰트를 복사 배포하지 않으므로 Android 글꼴의 픽셀 단위 일치는 보장하지 않습니다. OFL은 assets/fonts/OFL.txt에 포함합니다.
- 텍스트 줄높이는 ceil(size × 1.5), 기준선은 제공된 SVG의 size × 1.12 규칙을 따릅니다. 하단 탭 글자는 원본대로 중앙 정렬합니다.
- 실제 앱은 기기의 상태표시줄과 홈 인디케이터를 사용합니다. 원본의 가짜 9:41/배터리/홈바를 중복 표시하지 않습니다. 기기 안전 영역에 맞춰 비율을 유지하고, 작은 창에서는 스크롤합니다.
- 로그인은 원본에 없으므로 같은 색상·폰트·버튼 스타일로 정리했습니다.

## 동작과 데이터

검색창은 실제 이름/코드 입력과 빈 검색 결과를 지원합니다. 수량 +/-는 1주 단위이며 수량·가격을 눌러 직접 입력할 수 있습니다. 원본의 1주/5주 예시를 실제 입력으로 확장했습니다.

주문 확인은 기존 TradingController의 prepare → 서버 점검 → 최종 확인 → submit을 유지합니다. 차단 주문은 완료 화면에 진입하지 않습니다. 응답이 유실되면 전체 메뉴 → 계좌 카드 → 미확인 주문 복구에서 동일 idempotency key로 재확인합니다. TradePilot ON/OFF는 주문 팝업 하단에서 전환할 수 있습니다. 계좌 카드에서 로그아웃과 새로고침도 가능합니다.

원본의 지수·캔들·스파크라인은 디자인 예시입니다. 차트와 관심종목 안내에 예시임을 표시합니다. 서버 모드에서 수익률·자동매매 성과·계좌 평가금액·AI 데이터가 없으면 대기/빈 상태를 보여주며, 원본의 샘플 숫자를 실제 성과로 표시하지 않습니다. 최근 주문은 실제 repository의 주문 내역을 사용합니다. NAVER/Apple 시세는 서버에 없어 미연결로 표시합니다. 자동매매와 백테스트 엔진은 이번 UI 작업에서 구현하지 않았습니다.

## 검증

- Flutter 전체 테스트 20개: 원본 파일 일치, 35개 상태의 위젯/SVG 렌더링, 5개 탭, 검색과 무결과, 5주 주문, 주문 차단, 작은 화면 스크롤·키보드 입력, 서버 미연결 데이터 표시, 미확인 주문의 동일 키 복구, 기존 HTTP/WebSocket/컨트롤러 테스트.
- iPhone 17 / iOS 26.5에서 통합 테스트 통과. 35개 원본 상태와 실제 앱 흐름 9개 화면을 2배 해상도로 캡처했습니다.
- 원본 PNG와 Flutter 렌더를 나란히 비교해 글꼴·기준선·탭 정렬을 확인했습니다. 실제 기기의 안전 영역과 런타임 데이터는 원본 고정 시안과 다릅니다. 플랫폼 래스터라이저의 안티앨리어싱까지 동일하다고 주장하지 않습니다.
- iOS 디버그 빌드 및 Android ARM64 디버그 APK 빌드 성공. Android는 빌드 검증이며 실기기 시각 검증은 미실시입니다.
- 정적 분석과 포맷 검사 결과는 WORK_STATUS.md의 최신 기록을 참고하세요.

## 비교 파일

- [관심종목 원본(왼쪽) / Flutter(오른쪽)](design-review/compare-watchlist.png)
- [원본 상태 1–7 비교](design-review/contact-1.png)
- [원본 상태 8–14 비교](design-review/contact-2.png)
- [원본 상태 15–21 비교](design-review/contact-3.png)
- [원본 상태 22–28 비교](design-review/contact-4.png)
- [원본 상태 29–35 비교](design-review/contact-5.png)
- `design-review/app-*.png`: 실제 앱 흐름 화면 (상태표시줄은 OS 레이어라 위젯 캡처에 미포함)
- `design-review/reference-*.png`: 원본 390×844 시안의 순수 렌더링

## 다시 실행하기

이전 `/tmp` Flutter SDK는 삭제되어 `.tools/flutter`와 `.tools/pub-cache`로 복구했습니다. `.tools/`는 Git에서 제외됩니다. 저장소 복제만으로 SDK가 설치되지는 않습니다. 외부 SDK를 사용하려면 FLUTTER_ROOT를 지정하세요.

```sh
cd /Users/mumyon/Documents/TradePilot/client
./tool/flutterw run -d 415A659E-9A09-4C35-BABB-2FA140F9BDA8 --dart-define=DEMO_MODE=true
```

서버 연결 모드는 서버와 새 HTTPS 터널을 먼저 켜고 실행합니다. 예전 trycloudflare 주소는 더 이상 유효하지 않았습니다.

```sh
./tool/flutterw run -d 415A659E-9A09-4C35-BABB-2FA140F9BDA8 \
  --dart-define=DEMO_MODE=false \
  --dart-define=API_BASE_URL=https://YOUR-NEW-HOST.trycloudflare.com
```

재검증:

```sh
./tool/flutterw analyze
./tool/flutterw test
./tool/flutterw drive --driver=test_driver/design_driver.dart \
  --target=integration_test/design_visual_test.dart \
  -d 415A659E-9A09-4C35-BABB-2FA140F9BDA8
```

마지막 명령은 데모 데이터로 테스트하며 실제 서버에 주문을 넣지 않습니다. 비교 시트 재생성은 Pillow가 있는 Python으로 `python tool/compare_design.py`를 실행하세요.

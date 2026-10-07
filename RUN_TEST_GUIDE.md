# TradePilot 서버 + 앱 실행 안내

현재 Mac에서 Android 에뮬레이터로 테스트하는 순서입니다. 터미널 탭 3개를 사용합니다.

앱 → HTTPS/WSS 임시 주소 → FastAPI → PostgreSQL 순서로 연결합니다. 증권사 API는 미연결 상태이므로 서버의 가상 시세와 모의 주문으로 테스트합니다.

## 1. 처음 한 번 준비

- [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/)에서 Apple Silicon 버전을 설치하고 실행합니다. Docker 엔진이 실행될 때까지 기다립니다.
- Android Studio를 열고 Device Manager에서 Android 가상 기기를 시작합니다. 가상 기기가 없으면 Create Virtual Device로 하나 생성합니다.
- Flutter는 현재 `/tmp/tradepilot-flutter-sdk`에 있습니다. 임시 폴더가 삭제되면 Flutter SDK를 다시 설치하고 아래 PATH를 설치 위치로 바꿔야 합니다.

## 2. 터미널 1: DB와 서버 실행

```sh
cd /Users/mumyon/Documents/TradePilot/server
cp -n .env.compose.example .env
open -e .env
```

열린 `.env`를 다음처럼 설정하고 저장합니다. `YOUR_DB_PASSWORD` 두 곳에 같은 비밀번호를 넣으세요. 처음 테스트할 때는 영문과 숫자 조합을 쓰면 URL 인코딩 문제가 없습니다. 기존 `.env`가 있다면 위 복사 명령은 덮어쓰지 않습니다.

```dotenv
POSTGRES_PASSWORD=YOUR_DB_PASSWORD
DATABASE_URL=postgresql+psycopg://tradepilot:YOUR_DB_PASSWORD@db:5432/tradepilot
MARKET_DATA_MODE=demo
```

```sh
docker compose up --build -d
docker compose ps
```

첫 실행은 이미지 다운로드와 빌드 때문에 시간이 걸립니다. DB 생성과 마이그레이션은 자동입니다.

브라우저에서 다음을 확인합니다.

- http://localhost:8000/health/ready → `{"status":"ready"}`이면 서버와 DB 연결 성공
- http://localhost:8000/docs → API 확인 화면

테스트 계정은 최초 한 번 생성합니다.

```sh
docker compose exec api python -m app.cli create-user --email test@example.com --demo-holdings
```

12자 이상의 앱 로그인 비밀번호를 두 번 입력합니다. 입력 중 글자가 보이지 않는 것은 정상입니다. 이 비밀번호는 위 DB 비밀번호와 별개입니다. 이미 생성된 이메일로 다시 실행할 필요는 없습니다.

## 3. 터미널 2: 앱이 사용할 HTTPS 주소 생성

현재 앱은 HTTPS만 허용합니다. 로컬 HTTP 주소를 직접 넣으면 실행되지 않습니다. Cloudflare Quick Tunnel로 임시 HTTPS 주소를 받을 수 있습니다. 이 방식은 서버를 인터넷에 노출하고 Cloudflare를 통해 통신하므로 가상 테스트 데이터만 사용하고 테스트 후 종료하세요. [공식 Quick Tunnel 안내](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

최초 한 번 설치합니다. [공식 설치 안내](https://developers.cloudflare.com/tunnel/downloads/)

```sh
brew install cloudflared
```

실행합니다.

```sh
cloudflared tunnel --url http://localhost:8000
```

출력에 나온 `https://무작위이름.trycloudflare.com` 주소를 복사합니다. 이 터미널은 켜 두세요. 해당 주소 뒤에 `/health/ready`를 붙여 브라우저에서 열고 `ready`인지 확인합니다.

## 4. 터미널 3: Flutter 앱 실행

```sh
cd /Users/mumyon/Documents/TradePilot/client
export PATH="/tmp/tradepilot-flutter-sdk/bin:$PATH"
export PUB_CACHE=/tmp/tradepilot-pub-cache
flutter --no-version-check devices
```

Android 에뮬레이터가 목록에 보이면 아래 명령의 주소를 **3단계에서 받은 실제 주소**로 바꾸고 실행합니다.

```sh
flutter --no-version-check run \
  --dart-define=DEMO_MODE=false \
  --dart-define=API_BASE_URL=https://YOUR.trycloudflare.com
```

기기가 여러 개면 Android 에뮬레이터를 선택합니다. 주소 뒤에 `/v1`이나 `/docs`를 붙이지 마세요.

기존에 만든 APK는 앱 내부 데모 모드입니다. 서버 연결을 확인하려면 위 명령으로 다시 빌드해야 합니다. `DEMO_MODE=false`는 서버에 실제로 연결한다는 뜻이며, 서버의 `MARKET_DATA_MODE=demo`는 가상 시세를 사용한다는 뜻입니다.

## 5. 앱에서 확인할 내용

1. `test@example.com`과 2단계에서 만든 앱 비밀번호로 로그인합니다.
2. 관심종목에 삼성전자와 SK하이닉스가 나타나는지 확인합니다.
3. 시세 연결 상태와 갱신 시간을 확인합니다. 서버 데모 가격 자체는 고정되어 있으므로 가격이 그대로여도 정상입니다.
4. 삼성전자 1주 매수를 최종 확인까지 진행하고 주문 기록에 접수 결과가 남는지 확인합니다.
5. 삼성전자 20주 매수는 기본 1회 주문 한도 100만 원을 초과하므로 차단되는지 확인합니다.

현재 AI 예측과 캔들 데이터는 미연결이며, 주문은 모의 접수·예약까지 처리합니다. 실제 체결이 발생하지 않는 것은 정상입니다. 앱 내부 데모에서 보던 AI 샘플이 서버 연결 모드에서 제공되지 않을 수 있습니다.

## 6. 종료와 다음 실행

- 터미널 3: `q`를 눌러 Flutter 실행을 종료합니다.
- 터미널 2: `Ctrl+C`로 임시 HTTPS 주소를 종료합니다.
- 터미널 1에서 아래 명령으로 서버와 DB를 종료합니다. DB 데이터는 보존됩니다.

```sh
cd /Users/mumyon/Documents/TradePilot/server
docker compose down
```

다음에는 Docker Desktop과 에뮬레이터를 켜고 `docker compose up -d` → 터널 실행 → Flutter 실행 순서만 반복합니다. 계정은 다시 만들지 않습니다. 터널 주소는 매번 달라질 수 있으므로 새 주소로 Flutter를 다시 실행하세요. Hot Reload만으로는 주소 설정이 바뀌지 않습니다.

## 문제가 생겼을 때

| 증상 | 확인할 것 |
|---|---|
| `docker: command not found` | Docker Desktop 설치 여부 |
| Docker daemon 연결 실패 | Docker Desktop 실행 후 엔진 준비 여부 |
| 관심종목 시세가 비어 있음 | `.env`의 `MARKET_DATA_MODE=demo` 확인 후 `docker compose up -d api` |
| 로그인 실패 | 테스트 계정 생성 여부와 앱 비밀번호 확인 |
| HTTPS 설정 오류 | `API_BASE_URL`에 `https://` 주소만 입력했는지 확인 |
| 서버 연결 실패 | 로컬 `/health/ready`부터 확인하고 터널 프로세스 및 새 URL 확인 |
| Flutter에 기기가 없음 | Android Studio Device Manager에서 에뮬레이터 시작 |
| 로그인 없이 내부 데모가 보임 | `DEMO_MODE=false`를 넣고 앱 다시 실행 |
| DB 비밀번호 변경 후 접속 실패 | 기존 DB 볼륨의 비밀번호는 `.env` 변경으로 바뀌지 않음. 기존 비밀번호 복원 또는 별도 DB 비밀번호 변경 필요 |

서버 오류 로그는 다음으로 확인합니다.

```sh
cd /Users/mumyon/Documents/TradePilot/server
docker compose logs --tail=100 api migrate
```

iOS는 전체 Xcode 설치와 시뮬레이터 설정이 추가로 필요합니다. 현재 환경에서는 iOS 빌드를 검증하지 않았습니다.

이 안내는 프로젝트 설정에 맞춰 작성했습니다. 현재 Mac에서 Docker·터널·앱을 함께 실행하는 전체 연결 검증은 아직 수행하지 않았습니다.

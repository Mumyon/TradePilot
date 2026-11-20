# TradePilot 웹 시연

Flutter 웹은 모바일 앱과 같은 Dart 코드와 디자인을 사용한다. 시연 목적에 따라 브라우저 안에서 실행하는 화면 체험과 FastAPI 연결 시연 중 하나를 빌드한다.

| 방식 | 시연할 수 있는 범위 | 필요한 환경 |
| --- | --- | --- |
| 화면 체험 | 예시 시세, 차트 화면, 예시 주문 접수 | 정적 호스팅 |
| 서버 연결 | 로그인, 시세·차트, 주문 전 AI 피드백, 모의 주문·체결, 계정별 매매일지 | HTTPS FastAPI, PostgreSQL, 시세·AI 설정 |

화면 체험의 데이터는 예시이며 주문 내역은 브라우저에서 새로고침하면 초기화된다. 실제 체결과 AI 응답을 시연하려면 서버 연결 빌드를 사용한다.

## 로컬 화면 체험

```sh
cd client
./tool/flutterw build web --dart-define=DEMO_MODE=true
python3 -m http.server 8080 --bind 127.0.0.1 --directory build/web
```

브라우저에서 `http://127.0.0.1:8080`을 연다. 외부 참가자에게 제공하는 경우 `client/build/web/` 전체를 HTTPS 정적 호스팅에 올리고, 배포 주소를 QR에 연결한다.

## 서버 연결 빌드

### 모바일 앱과 같은 화면을 로컬에서 확인

프로젝트 루트의 첫 번째 터미널에서 토스 시세 서버를 시작한다.

```sh
ALLOWED_ORIGINS='["http://localhost:18083"]' ./tool/start_market_paper.sh \
  --provider toss --port 18084 --data-dir .demo/web-preview
```

두 번째 터미널에서 웹을 시작하고 브라우저에서 `http://localhost:18083`을 연다.

```sh
./tool/start_web_market_paper.sh
```

로컬 웹 검증은 모바일 앱의 기본 DB와 별도의 DB에서 진행한다. 웹에서 시연 계정을 만든 뒤 차트·주문 화면을 확인한다.

### 참가자에게 공개

참가자 시연에서는 FastAPI가 웹 화면도 제공할 수 있다. 브라우저·REST·WebSocket이 같은 HTTPS 주소를 사용한다. 프로젝트 루트에서 최신 모바일 앱 코드로 웹 릴리스를 빌드한다.

```sh
./tool/build_web_release.sh
```

배포용 압축 파일은 `client/build/tradepilot-web.tar.gz`에 생성된다. 서버에서 압축을 푼 디렉터리 또는 로컬의 `client/build/web`을 `WEB_BUILD_DIR`로 지정한다.

시연 서버의 환경 변수 또는 `server/.env`에 아래 항목을 설정한다.

| 키 | 값 |
| --- | --- |
| `WEB_BUILD_DIR` | 번들의 `index.html`이 있는 디렉터리의 절대 경로 |
| `ALLOWED_ORIGINS` | 참가자 주소 배열. 예시 `["https://demo.example.com"]` |
| `DATABASE_URL` | 참가자용 PostgreSQL |
| `MARKET_DATA_MODE` | `toss` |
| `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` | 서버에 저장한 시세 조회 키 |
| `PAPER_WORKER_ENABLED` | `true` |
| `AI_REVIEW_ENABLED` | `true` |
| `AI_REVIEW_PROVIDER` | `openai_api` |
| `OPENAI_API_KEY` | 시연 전용 OpenAI API 프로젝트 키 |
| `OPENAI_MODEL` | 기본값 `gpt-4.1-mini` |

`server/`에서 `./.venv/bin/alembic upgrade head`로 참가자 DB를 준비한 후 `./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18082 --no-access-log`를 실행한다. HTTPS를 처리하는 프록시는 `/`와 `/v1/ws`를 같은 FastAPI로 전달한다. 참가자는 앱과 같은 로그인 화면에서 계정을 만들고 차트, 주문 전 AI 피드백, 모의체결, 매매일지를 이용한다. 계정마다 기본 모의 자금으로 시작한다.

API 모드의 차트·주문 AI 요청은 계정당 최근 24시간 최대 12회다. 발급한 OpenAI 프로젝트의 사용량도 함께 확인한다. 주문 체결 조건은 기존 앱과 동일하게 현재 시장 시간, 시세의 신선도, 주문 가격에 따른다.

### 웹과 API를 별도 주소에서 제공할 경우

```sh
./tool/build_web_release.sh https://api.example.com
```

`API_BASE_URL`에는 경로 없이 실제 API 도메인을 사용한다. 아래 예시에서 정적 웹 주소는 `https://demo.example.com`이다.

기존 Sites 주소를 갱신할 경우 이 방식으로 빌드한 결과를 올린다. 배포 전에 API의 `/health/ready`가 외부에서 응답하는지 확인한다. API 주소를 변경하면 웹을 다시 빌드한다.

- FastAPI 운영 환경의 `ALLOWED_ORIGINS`에 웹 주소를 JSON 배열로 설정한다. 예시 `["https://demo.example.com"]`. HTTP CORS와 WebSocket Origin 검사에 같은 설정을 사용한다.
- API 앞의 프록시에서 WebSocket 업그레이드를 지원하도록 설정한다.
- PostgreSQL과 시세·AI 자격 증명은 서버에서 관리한다. 웹 빌드에 들어가는 API 주소는 공개 정보다.
- 참가자가 AI 분석을 요청할 시연에서는 참가자용 AI 연결 방식과 요청 한도를 별도로 준비한다. 현재 로컬 ChatGPT 연결을 참가자 사이에 공유하지 않는다.
- 외부 공개 전 시세 사용 조건과 인증·운영 항목을 [서버 문서](../../server/README.md)에서 확인한다.

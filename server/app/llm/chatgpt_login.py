"""Local interactive ChatGPT Plus connection, separate for each TradePilot user.

Run from server: python -m app.llm.chatgpt_login --demo --email <app-email>
Never paste tokens or passwords into chat. This program prompts locally.
"""

import argparse
import base64
import getpass
import hashlib
import html
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

from sqlalchemy import select

from ..config import Settings
from ..db import make_database
from ..models import User
from ..security import passwords
from . import chatgpt


def authorization(old, host_id, redirect_uri):
    verifier, state, nonce = (secrets.token_urlsafe(48) for _ in range(3))
    params = dict(
        client_id=old.get("client_id", "dynamic_agent_client"),
        ext_agent_host_id=host_id,
        response_type="code",
        redirect_uri=redirect_uri,
        scope=chatgpt.SCOPE,
        resource=chatgpt.RESOURCE,
        state=state,
        nonce=nonce,
        code_challenge_method="S256",
        code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("="),
    )
    if not old.get("client_id"):
        params["agent_name_hint"] = "TradePilot"
    elif old.get("id_token"):
        params["id_token_hint"] = old["id_token"]
    return dict(
        url=chatgpt.AUTH + "/api/accounts/authorize?" + urlencode(params),
        state=state,
        nonce=nonce,
        verifier=verifier,
        redirect_uri=redirect_uri,
        client_id=old.get("client_id"),
    )


def callback(query, pending):
    if any(len(v) != 1 for v in query.values()):
        raise chatgpt.ReviewError("callback_invalid")
    if not secrets.compare_digest(query.get("state", [""])[0], pending["state"]):
        raise chatgpt.ReviewError("callback_invalid")
    if query.get("error"):
        raise chatgpt.ReviewError("consent_required")
    issued = query.get("client_id", [pending["client_id"]])[0]
    if not issued or issued == "dynamic_agent_client":
        raise chatgpt.ReviewError("callback_invalid")
    if pending["client_id"] and pending["client_id"] != issued:
        raise chatgpt.ReviewError("callback_invalid")
    code = query.get("code", [""])[0]
    if not code:
        raise chatgpt.ReviewError("callback_invalid")
    return issued, code


def login(directory, user_id, *, no_browser=False, choose_model=None):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    host_file = root / "host.json"
    # Stable per runtime, even if sign-in fails or the app restarts.
    with chatgpt.credential_lock(host_file):
        if not host_file.exists():
            chatgpt.write_private(host_file, {"host_id": "urn:uuid:" + str(uuid4())})
        host = chatgpt.read_private(host_file)["host_id"]
    path = chatgpt.credential_path(root, user_id)
    with chatgpt.credential_lock(path):
        old = chatgpt.read_private(path) if path.exists() else {}
        result = {}
        pending = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Callback URLs contain authorization codes.

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/start":
                    body = (
                        '<!doctype html><meta charset="utf-8"><h1>TradePilot</h1>'
                        "<p>본인 ChatGPT 구독으로 종료 후 AI 복기를 생성합니다.</p>"
                        '<a data-oai-siwc-button href="'
                        + html.escape(pending["url"], quote=True)
                        + '">Continue with ChatGPT</a>'
                    ).encode()
                    self.send_response(200)
                elif parsed.path == "/auth/callback":
                    try:
                        result["registration"] = callback(parse_qs(parsed.query), pending)
                        self.send_response(200)
                        body = "로그인 응답을 받았습니다. 터미널에서 검증을 완료합니다.".encode()
                    except chatgpt.ReviewError:
                        self.send_response(400)
                        body = "로그인이 완료되지 않았습니다. 터미널에서 다시 시작하세요.".encode()
                        result["error"] = True
                else:
                    self.send_response(404)
                    body = b"Not found"
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
            pending.update(authorization(old, host, redirect))
            start_url = f"http://127.0.0.1:{server.server_port}/start"
            print("브라우저에서 Continue with ChatGPT를 선택하세요: " + start_url, flush=True)
            if not no_browser:
                webbrowser.open(start_url)
            server.timeout = 1
            deadline = time.monotonic() + 180
            while not result and time.monotonic() < deadline:
                server.handle_request()
        if "registration" not in result:
            raise chatgpt.ReviewError("login_not_completed")
        issued, code = result["registration"]
        with chatgpt.client() as http:
            response = http.post(
                chatgpt.TOKEN_URL,
                data=dict(
                    grant_type="authorization_code",
                    client_id=issued,
                    code=code,
                    code_verifier=pending["verifier"],
                    redirect_uri=redirect,
                    resource=chatgpt.RESOURCE,
                ),
            )
            if response.status_code != 200:
                raise chatgpt.ReviewError("login_not_completed")
            tokens = response.json()
        record = chatgpt.checked_tokens(
            tokens, issued, nonce=pending["nonce"], subject=old.get("subject")
        )
        available = chatgpt.models(record["access_token"])
        if not available:
            raise chatgpt.ReviewError("model_required")
        for i, model in enumerate(available, 1):
            print(f"{i}. {model.get('display_name', model['slug'])} ({model['slug']})")
        if choose_model:
            selected = choose_model
        else:
            answer = input("사용할 모델 번호: ").strip()
            if not answer.isdigit() or not 1 <= int(answer) <= len(available):
                raise chatgpt.ReviewError("model_required")
            selected = available[int(answer) - 1]["slug"]
        if selected not in {m["slug"] for m in available}:
            raise chatgpt.ReviewError("model_required")
        record.update(user_id=user_id, model=selected, host_id=host)
        chatgpt.write_private(path, record)
        print(
            "연결 완료. 토큰은 보호된 로컬 파일에 저장했습니다. 앱에서 연결 상태를 새로고침하세요."
        )


def disconnect(directory, user_id):
    path = chatgpt.credential_path(directory, user_id)
    with chatgpt.credential_lock(path):
        record = chatgpt.read_private(path)
        revoked = False
        try:
            with chatgpt.client() as http:
                discovery = http.get(chatgpt.AUTH + "/.well-known/openid-configuration")
                discovery.raise_for_status()
                endpoint = discovery.json()["revocation_endpoint"]
                if not endpoint.startswith(chatgpt.AUTH + "/"):
                    raise ValueError("Unexpected revocation host")
                response = http.post(
                    endpoint,
                    data=dict(
                        token=record.get("refresh_token", ""),
                        token_type_hint="refresh_token",
                        client_id=record["client_id"],
                    ),
                )
                revoked = response.status_code == 200
        except Exception:
            revoked = False
        finally:
            retained = {
                k: record[k] for k in ("client_id", "subject", "user_id", "model", "host_id")
            }
            retained["scopes"] = []
            chatgpt.write_private(path, retained)
        print(
            "로컬 연결 해제 완료."
            + ("" if revoked else " 원격 해제는 ChatGPT 설정에서도 확인하세요.")
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", required=True, help="TradePilot login email, not ChatGPT credentials"
    )
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--disconnect", action="store_true")
    args = parser.parse_args()
    if args.demo:
        import pgserver

        folder = Path(__file__).resolve().parents[2] / ".demo/postgres"
        if not (folder / "PG_VERSION").exists():
            parser.error("먼저 로컬 모의투자 서버를 실행하세요.")
        postgres = pgserver.get_server(folder, cleanup_mode=None)
        url = postgres.get_uri().replace("postgresql:", "postgresql+psycopg:", 1)
        settings = Settings(
            database_url=url, chatgpt_credentials_dir=folder.parent / "chatgpt", _env_file=None
        )
    else:
        settings = Settings()
    engine, sessions = make_database(settings.database_url.get_secret_value())
    try:
        with sessions() as db:
            user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
            password = getpass.getpass("TradePilot 앱 비밀번호 (화면에 표시되지 않음): ")
            if (
                user is None
                or not user.enabled
                or not passwords.verify(password, user.password_hash)
            ):
                parser.error("앱 계정을 확인하세요.")
            user_id = user.id
        if args.disconnect:
            disconnect(settings.chatgpt_credentials_dir, user_id)
        else:
            login(
                settings.chatgpt_credentials_dir,
                user_id,
                no_browser=args.no_browser,
                choose_model=args.model,
            )
    except Exception as exc:
        code = exc.code if isinstance(exc, chatgpt.ReviewError) else "connection_failed"
        print("연결을 완료하지 못했습니다: " + code)
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

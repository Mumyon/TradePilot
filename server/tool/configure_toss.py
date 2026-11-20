"""Store Toss Open API client credentials in the local server .env file."""

import getpass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def main():
    client_id = input("토스 Client ID (tsck_live_...): ").strip()
    client_secret = getpass.getpass("토스 Client Secret (화면에 표시되지 않음): ").strip()
    if not client_id or not client_secret or any(c in client_id + client_secret for c in "\r\n"):
        raise SystemExit("Client ID와 Client Secret을 입력해야 합니다.")
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    values = {
        "MARKET_DATA_MODE": "toss",
        "TOSS_CLIENT_ID": client_id,
        "TOSS_CLIENT_SECRET": client_secret,
    }
    keys = set(values)
    lines = [line for line in lines if line.split("=", 1)[0] not in keys]

    def quote(value):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines.extend(f"{key}={quote(value)}" for key, value in values.items())
    temporary = ENV_FILE.with_suffix(".env.tmp")
    temporary.write_text("\n".join(lines) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(ENV_FILE)
    print("토스 시세 설정을 server/.env에 저장했습니다. 값은 출력하지 않았습니다.")
    print("WTS의 허용 IP에 서버가 호출하는 현재 공인 IP를 등록한 뒤 compose를 재시작하세요.")


if __name__ == "__main__":
    main()

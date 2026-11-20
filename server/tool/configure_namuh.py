"""Interactive local-only key entry; never prints or sends credentials."""

import argparse
import getpass
import json
import os
import subprocess
import tempfile
from pathlib import Path


def clipboard_value(label):
    input(f"나무 PLUG에서 {label} 전체 값을 복사(Command+C)한 뒤 여기서 Enter를 누르세요: ")
    try:
        value = subprocess.run(
            ["/usr/bin/pbpaste"], check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise SystemExit("클립보드를 읽지 못했습니다. 저장하지 않았습니다.") from None
    if not value:
        raise SystemExit("클립보드가 비어 있습니다. 저장하지 않았습니다.")
    print(f"{label} 복사 값 확인 완료 (값은 표시하지 않습니다).")
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace", action="store_true", help="기존 로컬 키를 새 입력으로 교체")
    parser.add_argument("--clipboard", action="store_true", help="macOS 클립보드에서 키 읽기")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / ".env.namuh"
    if target.exists() and not args.replace:
        raise SystemExit("server/.env.namuh가 이미 있습니다. 필요한 변경은 파일을 직접 편집하세요.")
    if args.clipboard:
        key = clipboard_value("App Key")
        secret = clipboard_value("App Secret")
        if key == secret:
            raise SystemExit(
                "두 값이 같습니다. App Secret을 새로 복사해 다시 진행하세요. 저장하지 않았습니다."
            )
    else:
        key = getpass.getpass("나무 PLUG App Key (붙여넣기 Command+V 가능, 입력 숨김): ").strip()
        secret = getpass.getpass(
            "나무 PLUG App Secret (붙여넣기 Command+V 가능, 입력 숨김): "
        ).strip()
    if not key or not secret or any(c in key + secret for c in "\r\n\x00'"):
        raise SystemExit("키가 비어 있거나 허용되지 않는 문자가 있습니다. 저장하지 않았습니다.")
    symbols = ["005930", "000660"]
    if target.exists():
        from dotenv import dotenv_values

        symbols = json.loads(dotenv_values(target).get("NHPLUG_SYMBOLS", json.dumps(symbols)))
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".env.namuh-")
    with os.fdopen(fd, "w") as handle:
        handle.write("# 나무 실제 시세 전용. 실주문·계좌번호 설정 없음.\n")
        handle.write(f"NHPLUG_APP_KEY='{key}'\nNHPLUG_APP_SECRET='{secret}'\n")
        handle.write("NHPLUG_SYMBOLS=" + json.dumps(symbols) + "\n")
    os.replace(temporary, target)
    print("server/.env.namuh에 권한 600으로 저장했습니다. 키는 화면에 출력하지 않습니다.")
    print("프로젝트 루트에서 ./tool/start_market_paper.sh 를 실행하세요.")


if __name__ == "__main__":
    main()

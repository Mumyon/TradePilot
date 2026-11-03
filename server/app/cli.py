"""Local admin only; no public registration or funding endpoint."""

import argparse
import getpass

from sqlalchemy import select

from .config import Settings
from .db import make_database
from .models import Holding, Symbol, User, Watchlist
from .security import passwords


def create_user(db, email: str, password: str, demo_holdings=False) -> User:
    email = email.strip().lower()
    if not 3 <= len(email) <= 254 or "@" not in email:
        raise ValueError("올바른 이메일을 입력하세요.")
    if not 12 <= len(password) <= 256:
        raise ValueError("비밀번호는 12~256자로 입력하세요.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise ValueError("이미 등록된 이메일입니다.")
    for symbol, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
        if db.get(Symbol, symbol) is None:
            db.add(Symbol(symbol=symbol, name=name))
    db.flush()
    user = User(email=email, password_hash=passwords.hash(password))
    db.add(user)
    db.flush()
    for symbol in ["005930", "000660"]:
        db.add(Watchlist(user_id=user.id, symbol=symbol))
        if demo_holdings:
            db.add(
                Holding(
                    user_id=user.id,
                    symbol=symbol,
                    quantity=100,
                    cost_won={"005930": 7_280_000, "000660": 17_350_000}[symbol],
                )
            )
    return user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create-user"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--demo-holdings", action="store_true")
    args = parser.parse_args()
    password = getpass.getpass("새 계정 비밀번호 (12자 이상): ")
    if password != getpass.getpass("비밀번호 확인: "):
        raise SystemExit("비밀번호가 일치하지 않습니다.")
    engine, sessions = make_database(Settings().database_url.get_secret_value())
    try:
        with sessions.begin() as db:
            user = create_user(db, args.email, password, args.demo_holdings)
            user_id = user.id
        print(f"모의투자 계정 생성 완료: {user_id}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

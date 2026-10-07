import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import AuthSession, User, WsTicket, now

passwords = PasswordHash.recommended()
_dummy_hash = passwords.hash("unused-password-for-uniform-verification")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate(db: Session, token_hash: str) -> str:
    record = db.get(AuthSession, token_hash)
    user = db.get(User, record.user_id) if record else None
    if record is None or record.expires_at <= now() or user is None or not user.enabled:
        raise HTTPException(401, "로그인이 필요합니다.", headers={"WWW-Authenticate": "Bearer"})
    return user.id


def login(db: Session, email: str, password: str, ttl: int) -> dict:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    verified = passwords.verify(password, user.password_hash if user else _dummy_hash)
    if not verified or user is None or not user.enabled:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인하세요.")
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(seconds=ttl)
        )
    )
    return {"access_token": token, "user_id": user.id}


def issue_ticket(db: Session, session_hash: str, ttl: int) -> str:
    authenticate(db, session_hash)
    ticket = secrets.token_urlsafe(32)
    db.add(
        WsTicket(
            token_hash=digest(ticket),
            session_hash=session_hash,
            expires_at=now() + timedelta(seconds=ttl),
        )
    )
    return ticket


def consume_ticket(db: Session, ticket: str) -> tuple[str, str]:
    # Atomic across all API workers: only one handshake can consume a ticket.
    session_hash = db.scalar(
        delete(WsTicket)
        .where(WsTicket.token_hash == digest(ticket), WsTicket.expires_at > now())
        .returning(WsTicket.session_hash)
    )
    if session_hash is None:
        raise HTTPException(401, "WebSocket 티켓이 만료되었거나 사용되었습니다.")
    return authenticate(db, session_hash), session_hash

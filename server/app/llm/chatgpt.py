"""Official Sign in with ChatGPT credentials and streamed Responses transport.

Only api.openai.com/v1 and auth.openai.com are contacted. No Codex credentials
are read and there is no API-key or paid-provider fallback.
"""

import fcntl
import json
import os
import secrets
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

AUTH = "https://auth.openai.com"
TOKEN_URL = AUTH + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"


class ReviewError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def client():
    try:
        import httpx
    except ImportError:
        raise ReviewError("setup_required") from None
    # Do not follow redirects carrying authorization; never retry billed requests.
    return httpx.Client(timeout=15, follow_redirects=False)


def credential_path(directory, user_id):
    UUID(user_id)
    return Path(directory) / f"{user_id}.json"


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ReviewError("credential_permissions")
        with os.fdopen(fd, "r", closefd=False) as stream:
            return json.load(stream)
    finally:
        os.close(fd)


def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def credential_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReviewError("connection_busy") from None
        yield
    finally:
        os.close(fd)


def validate_identity(id_token, client_id, *, nonce=None, subject=None):
    try:
        import jwt

        with client() as http:
            response = http.get(AUTH + "/.well-known/jwks.json")
            response.raise_for_status()
            keys = response.json()["keys"]
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256":
            raise ReviewError("identity_invalid")
        jwk = next(k for k in keys if k.get("kid") == header.get("kid"))
        claims = jwt.decode(
            id_token,
            jwt.PyJWK.from_dict(jwk).key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=AUTH,
            leeway=5,
            options={"require": ["sub", "exp", "iat", "aud", "iss"]},
        )
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ReviewError("identity_invalid")
        if nonce is not None and claims.get("nonce") != nonce:
            raise ReviewError("identity_invalid")
        if subject is not None and claims["sub"] != subject:
            raise ReviewError("identity_invalid")
        return claims
    except ReviewError:
        raise
    except ImportError:
        raise ReviewError("setup_required") from None
    except Exception:
        raise ReviewError("identity_invalid") from None


def checked_tokens(tokens, client_id, *, nonce=None, subject=None):
    claims = validate_identity(tokens.get("id_token", ""), client_id, nonce=nonce, subject=subject)
    scopes = tokens.get("scope", "").split()
    if DIRECT_SCOPE not in scopes or not tokens.get("access_token"):
        raise ReviewError("consent_required")
    expires = tokens.get("expires_in")
    if not isinstance(expires, (int, float)) or not 0 < expires <= 86400:
        raise ReviewError("identity_invalid")
    return dict(
        client_id=client_id,
        subject=claims["sub"],
        scopes=scopes,
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        id_token=tokens["id_token"],
        expires_at=time.time() + expires,
    )


def connection(directory, user_id):
    try:
        record = read_private(credential_path(directory, user_id))
        if record["user_id"] != user_id or DIRECT_SCOPE not in record["scopes"]:
            raise ReviewError("consent_required")
        if not record.get("model"):
            raise ReviewError("model_required")
        if not record.get("access_token") or not isinstance(record.get("expires_at"), (int, float)):
            raise ReviewError("not_connected")
        if record["expires_at"] <= time.time() and not record.get("refresh_token"):
            raise ReviewError("reauth_required")
        return record
    except ReviewError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ReviewError("not_connected") from None


def access(directory, user_id):
    path = credential_path(directory, user_id)
    with credential_lock(path):
        record = connection(directory, user_id)
        if record["expires_at"] > time.time() + 60:
            return record
        if not record.get("refresh_token"):
            raise ReviewError("reauth_required")
        with client() as http:
            response = http.post(
                TOKEN_URL,
                data=dict(
                    grant_type="refresh_token",
                    client_id=record["client_id"],
                    refresh_token=record["refresh_token"],
                    resource=RESOURCE,
                ),
            )
            if response.status_code != 200:
                raise ReviewError("reauth_required")
            tokens = response.json()
        # OAuth permits omission of unchanged scopes and ID token on refresh.
        tokens.setdefault("scope", " ".join(record["scopes"]))
        if tokens.get("id_token"):
            renewed = checked_tokens(tokens, record["client_id"], subject=record["subject"])
        else:
            expires = tokens.get("expires_in")
            if (
                not tokens.get("access_token")
                or not isinstance(expires, (int, float))
                or not 0 < expires <= 86400
            ):
                raise ReviewError("reauth_required")
            renewed = dict(
                record,
                access_token=tokens["access_token"],
                expires_at=time.time() + expires,
            )
            if DIRECT_SCOPE not in tokens["scope"].split():
                raise ReviewError("consent_required")
        renewed["refresh_token"] = tokens.get("refresh_token") or record["refresh_token"]
        record.update(renewed)
        write_private(path, record)
        return record


def models(access_token):
    with client() as http:
        response = http.get(
            RESOURCE + "/models", headers={"Authorization": f"Bearer {access_token}"}
        )
        if response.status_code != 200:
            raise ReviewError("model_required")
        return [m for m in response.json().get("models", []) if m.get("visibility") == "list"]


def completed_response(events):
    """Never accept a delta or [DONE] without a completed terminal response."""
    size = 0
    for line in events:
        size += len(line)
        if size > 131072:
            raise ReviewError("response_invalid")
        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
            continue
        event = json.loads(line[5:].strip())
        if event.get("type") in ("response.failed", "response.incomplete", "error"):
            code = (event.get("response", {}).get("error") or event.get("error") or {}).get("code")
            if code in (
                "subscription_sharing_usage_limit_exceeded",
                "subscription_sharing_usage_unavailable",
            ):
                raise ReviewError("usage_limit")
            raise ReviewError("provider_failed")
        if event.get("type") == "response.completed":
            response = event["response"]
            if response.get("status") != "completed":
                raise ReviewError("provider_failed")
            return response
    raise ReviewError("stream_interrupted")


def generate(directory, user_id, requested_model, instructions, payload, schema):
    started = time.monotonic()
    try:
        record = access(directory, user_id)
        # A queued job is bound to the selected model, even if settings change later.
        body = dict(
            model=requested_model,
            instructions=instructions,
            input=[dict(role="user", content=json.dumps(payload, ensure_ascii=False))],
            text=dict(
                format=dict(
                    type="json_schema", name="tradepilot_review", strict=True, schema=schema
                )
            ),
            store=False,
            stream=True,
        )
        with client() as http:
            with http.stream(
                "POST",
                RESOURCE + "/responses",
                json=body,
                headers={"Authorization": f"Bearer {record['access_token']}"},
            ) as response:
                if response.status_code in (401, 403):
                    raise ReviewError("reauth_required")
                if response.status_code == 429:
                    raise ReviewError("usage_limit")
                if response.status_code != 200:
                    raise ReviewError("provider_failed")

                def lines():
                    for line in response.iter_lines():
                        if time.monotonic() - started > 45:
                            raise ReviewError("timeout")
                        yield line

                result = completed_response(lines())
        text = "".join(
            c.get("text", "")
            for item in result.get("output", [])
            if item.get("type") == "message"
            for c in item.get("content", [])
            if c.get("type") == "output_text"
        )
        return dict(
            content=json.loads(text),
            response_id=result["id"],
            response_model=result.get("model", requested_model),
            usage=result.get("usage", {}),
            latency_ms=round((time.monotonic() - started) * 1000),
        )
    except ReviewError:
        raise
    except Exception:
        # No tokens, provider response bodies, or account identities in public errors/logs.
        raise ReviewError("provider_failed") from None

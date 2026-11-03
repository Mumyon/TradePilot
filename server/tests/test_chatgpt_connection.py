import json
import os
import time
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.llm import chatgpt, chatgpt_login


def test_pkce_registration_state_and_returning_client_binding():
    pending = chatgpt_login.authorization(
        {}, "urn:uuid:" + str(uuid4()), "http://127.0.0.1:1455/auth/callback"
    )
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(pending["url"]).query)
    assert query["client_id"] == ["dynamic_agent_client"]
    assert query["agent_name_hint"] == ["TradePilot"]
    assert query["scope"][0] == chatgpt.SCOPE
    assert query["code_challenge_method"] == ["S256"]
    assert pending["verifier"] not in pending["url"]
    assert chatgpt_login.callback(
        dict(state=[pending["state"]], client_id=["issued"], code=["code"]), pending
    ) == ("issued", "code")
    with pytest.raises(chatgpt.ReviewError):
        chatgpt_login.callback(dict(state=["wrong"], client_id=["issued"], code=["code"]), pending)
    with pytest.raises(chatgpt.ReviewError):
        chatgpt_login.callback(dict(state=[pending["state"]], code=["code"]), pending)
    returning = chatgpt_login.authorization(
        dict(client_id="issued", id_token="private-id"), "host", pending["redirect_uri"]
    )
    assert "agent_name_hint" not in returning["url"]
    with pytest.raises(chatgpt.ReviewError):
        chatgpt_login.callback(
            dict(state=[returning["state"]], client_id=["other"], code=["code"]), returning
        )


def test_id_token_signature_issuer_audience_expiry_nonce_and_permission(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk["kid"] = "test"

    def handle(request):
        assert str(request.url) == chatgpt.AUTH + "/.well-known/jwks.json"
        return httpx.Response(200, json={"keys": [jwk]})

    monkeypatch.setattr(
        chatgpt, "client", lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )
    claims = dict(
        sub="person",
        iss=chatgpt.AUTH,
        aud="issued",
        iat=int(time.time()),
        exp=int(time.time()) + 300,
        nonce="nonce",
    )

    def encoded(value):
        return jwt.encode(value, private, algorithm="RS256", headers={"kid": "test"})

    tokens = dict(
        id_token=encoded(claims),
        access_token="fake-access",
        refresh_token="fake-refresh",
        scope=chatgpt.SCOPE,
        expires_in=300,
    )
    assert chatgpt.checked_tokens(tokens, "issued", nonce="nonce")["subject"] == "person"
    for change in [
        dict(iss="other"),
        dict(aud="other"),
        dict(exp=int(time.time()) - 60),
        dict(nonce="wrong"),
        dict(sub=""),
    ]:
        with pytest.raises(chatgpt.ReviewError, match="identity_invalid"):
            chatgpt.checked_tokens(
                {**tokens, "id_token": encoded({**claims, **change})}, "issued", nonce="nonce"
            )
    with pytest.raises(chatgpt.ReviewError, match="consent_required"):
        chatgpt.checked_tokens({**tokens, "scope": "openid"}, "issued", nonce="nonce")
    with pytest.raises(chatgpt.ReviewError, match="identity_invalid"):
        chatgpt.checked_tokens(tokens, "issued", subject="other")


def test_private_credentials_per_account_and_no_symlink(tmp_path):
    owner = str(uuid4())
    path = chatgpt.credential_path(tmp_path, owner)
    chatgpt.write_private(
        path,
        dict(
            user_id=owner,
            model="test",
            scopes=[chatgpt.DIRECT_SCOPE],
            access_token="fake",
            expires_at=time.time() + 300,
        ),
    )
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert chatgpt.connection(tmp_path, owner)["model"] == "test"
    with pytest.raises(chatgpt.ReviewError, match="not_connected"):
        chatgpt.connection(tmp_path, str(uuid4()))
    os.chmod(path, 0o644)
    with pytest.raises(chatgpt.ReviewError, match="credential_permissions"):
        chatgpt.connection(tmp_path, owner)
    os.chmod(path, 0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        chatgpt.read_private(link)


def test_refresh_is_persisted_and_uses_issued_client_not_registration(tmp_path, monkeypatch):
    uid = str(uuid4())
    path = chatgpt.credential_path(tmp_path, uid)
    record = dict(
        user_id=uid,
        client_id="issued",
        subject="person",
        model="test",
        scopes=chatgpt.SCOPE.split(),
        access_token="expired",
        refresh_token="old",
        expires_at=0,
    )
    chatgpt.write_private(path, record)
    calls = []

    def handle(request):
        calls.append(request)
        assert b"client_id=issued" in request.content and b"refresh_token=old" in request.content
        return httpx.Response(
            200, json=dict(access_token="renewed", refresh_token="rotated", expires_in=300)
        )

    monkeypatch.setattr(
        chatgpt, "client", lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )
    assert chatgpt.access(tmp_path, uid)["access_token"] == "renewed"
    assert chatgpt.access(tmp_path, uid)["refresh_token"] == "rotated"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "events,code",
    [
        (
            [{"type": "response.output_text.delta", "delta": "plausible answer"}],
            "stream_interrupted",
        ),
        (
            [
                {
                    "type": "response.failed",
                    "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}},
                }
            ],
            "usage_limit",
        ),
        ([{"type": "response.incomplete", "response": {}}], "provider_failed"),
    ],
)
def test_only_completed_streams_accepted(events, code):
    with pytest.raises(chatgpt.ReviewError, match=code):
        chatgpt.completed_response(["data: " + json.dumps(e) for e in events] + ["data: [DONE]"])


def test_responses_request_uses_only_official_endpoint_and_no_paid_fallback(monkeypatch):
    monkeypatch.setattr(chatgpt, "access", lambda *_: dict(access_token="fake-credential"))
    calls = []
    completed = dict(
        id="test-response",
        model="snapshot",
        status="completed",
        output=[
            dict(type="message", content=[dict(type="output_text", text='{"observations":[]}')])
        ],
        usage={},
    )

    def handle(request):
        calls.append(request)
        body = json.loads(request.content)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert body["model"] == "selected" and body["store"] is False and body["stream"] is True
        assert isinstance(body["input"], list)
        assert not set(body) & {"max_output_tokens", "temperature", "previous_response_id", "tools"}
        return httpx.Response(
            200,
            content=(
                "data: " + json.dumps(dict(type="response.completed", response=completed)) + "\n\n"
            ).encode(),
        )

    monkeypatch.setattr(
        chatgpt, "client", lambda: httpx.Client(transport=httpx.MockTransport(handle))
    )
    result = chatgpt.generate("unused", "owner", "selected", "instructions", {"facts": []}, {})
    assert result["response_id"] == "test-response" and len(calls) == 1
    monkeypatch.setattr(
        chatgpt,
        "client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429))),
    )
    with pytest.raises(chatgpt.ReviewError, match="usage_limit"):
        chatgpt.generate("unused", "owner", "selected", "instructions", {"facts": []}, {})


def test_disconnect_clears_tokens_even_when_remote_revocation_fails(tmp_path, monkeypatch, capsys):
    uid = str(uuid4())
    path = chatgpt.credential_path(tmp_path, uid)
    chatgpt.write_private(
        path,
        dict(
            user_id=uid,
            client_id="issued",
            subject="person",
            model="test",
            host_id="host",
            scopes=chatgpt.SCOPE.split(),
            access_token="secret",
            refresh_token="secret",
        ),
    )

    def fail(_):
        raise httpx.ConnectError("network unavailable")

    monkeypatch.setattr(
        chatgpt, "client", lambda: httpx.Client(transport=httpx.MockTransport(fail))
    )
    chatgpt_login.disconnect(tmp_path, uid)
    retained = chatgpt.read_private(path)
    assert retained["client_id"] == "issued" and retained["scopes"] == []
    assert not set(retained) & {"access_token", "refresh_token", "id_token"}
    assert "원격 해제는 ChatGPT 설정에서도 확인" in capsys.readouterr().out

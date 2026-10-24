"""``ApiService`` token renewal and ``KeycloakAuth`` grants.

HTTP is faked at ``requests.request`` / ``requests.post``; the token source is
a fake standing in for ``KeycloakAuth``.
"""

import base64
import hashlib
import hmac
import json
import threading
from urllib.parse import parse_qs

import pytest
import requests

from promptstorepy import PromptStore
from promptstorepy.ApiService import ApiService
from promptstorepy.CognitoAuth import CognitoAuth
from promptstorepy.KeycloakAuth import KeycloakAuth

URL = "http://promptstore.invalid/api/prompt-sets"


def _response(status, body=None, url=URL):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body if body is not None else {}).encode()
    response.url = url
    return response


class _Server:
    """Answers 200 only to ``Bearer <valid>``; records each Authorization."""

    def __init__(self, valid="fresh", forbidden=False):
        self.valid = valid
        self.forbidden = forbidden
        self.auth_headers = []
        self.lock = threading.Lock()

    def __call__(self, method, url, **kwargs):
        auth = kwargs["headers"].get("Authorization")
        with self.lock:
            self.auth_headers.append(auth)
        if self.forbidden:
            return _response(403, url=url)
        return _response(200 if auth == f"Bearer {self.valid}" else 401, {"ok": True}, url)


class _TokenSource:
    def __init__(self, refreshed=None, granted=None, refresh_error=None, grant_error=None):
        self.refreshed = refreshed or {"access_token": "fresh", "refresh_token": "r2"}
        self.granted = granted or {"access_token": "fresh"}
        self.refresh_error = refresh_error
        self.grant_error = grant_error
        self.refresh_calls = []
        self.grant_calls = 0

    def refresh(self, token):
        self.refresh_calls.append(token["refresh_token"])
        if self.refresh_error:
            raise self.refresh_error
        return self.refreshed

    def get_access_token(self):
        self.grant_calls += 1
        if self.grant_error:
            raise self.grant_error
        return self.granted


@pytest.fixture
def server(monkeypatch):
    fake = _Server()
    monkeypatch.setattr("promptstorepy.ApiService.requests.request", fake)
    return fake


def _service(source, token=None):
    api = ApiService(token_source=source)
    api.set_token(token or {"access_token": "stale", "refresh_token": "r1"})
    return api


def test_401_refreshes_once_and_retries_with_the_new_token(server):
    source = _TokenSource()
    api = _service(source)
    refreshed = []
    api.on_refresh(refreshed.append)

    assert api.get(URL).json() == {"ok": True}

    assert source.refresh_calls == ["r1"]
    assert server.auth_headers == ["Bearer stale", "Bearer fresh"]
    # stored with Keycloak's snake_case keys, so later requests use it
    assert api.get_access_token() == "fresh" and api.get_refresh_token() == "r2"
    assert refreshed == [source.refreshed]
    api.get(URL)
    assert server.auth_headers[-1] == "Bearer fresh"


def test_without_a_refresh_token_a_new_token_is_granted(server):
    source = _TokenSource()
    api = _service(source, {"access_token": "stale"})  # client_credentials: no refresh token

    api.get(URL)

    assert source.refresh_calls == [] and source.grant_calls == 1


def test_a_rejected_refresh_token_falls_back_to_a_new_grant(server):
    source = _TokenSource(refresh_error=requests.HTTPError("400 invalid_grant"))
    api = _service(source)

    api.get(URL)

    assert source.refresh_calls == ["r1"] and source.grant_calls == 1


def test_still_401_after_renewal_raises_without_looping(server):
    server.valid = "never"
    source = _TokenSource()
    api = _service(source)

    with pytest.raises(requests.HTTPError) as exc:
        api.get(URL)

    assert exc.value.response.status_code == 401
    assert len(server.auth_headers) == 2
    assert source.refresh_calls == ["r1"] and source.grant_calls == 0


def test_failed_renewal_raises_the_401_as_a_request_exception(server):
    source = _TokenSource(
        refresh_error=requests.HTTPError("400 invalid_grant"),
        grant_error=requests.ConnectionError("keycloak down"),
    )
    api = _service(source)
    expired = []
    api.on_expiry(expired.append)

    with pytest.raises(requests.RequestException) as exc:
        api.get(URL)

    assert exc.value.response.status_code == 401
    assert "keycloak down" in str(exc.value)
    assert isinstance(exc.value.__cause__, requests.ConnectionError)
    assert len(expired) == 1


def test_403_is_never_retried(server):
    server.forbidden = True
    source = _TokenSource()
    api = _service(source)

    with pytest.raises(requests.HTTPError) as exc:
        api.get(URL)

    assert exc.value.response.status_code == 403
    assert len(server.auth_headers) == 1
    assert source.refresh_calls == [] and source.grant_calls == 0


def test_api_key_auth_does_not_attempt_renewal(server, monkeypatch):
    monkeypatch.setenv("PROMPTSTORE_API_KEY", "key")
    source = _TokenSource()
    api = ApiService(token_source=source)  # no token set: apikey header

    with pytest.raises(requests.HTTPError):
        api.get(URL)

    assert source.refresh_calls == [] and source.grant_calls == 0


def test_concurrent_401s_renew_the_token_once(server):
    source = _TokenSource()
    api = _service(source)
    start = threading.Barrier(8)
    errors = []

    def call():
        start.wait()
        try:
            api.get(URL)
        except Exception as err:  # pragma: no cover - surfaced below
            errors.append(err)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert errors == []
    assert len(source.refresh_calls) + source.grant_calls == 1


def test_caller_headers_are_kept_and_not_mutated(server):
    api = _service(_TokenSource())
    headers = {"X-Trace": "1"}

    api.get(URL, headers=headers)

    assert headers == {"X-Trace": "1"}


# ---- KeycloakAuth ----

class _Keycloak:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body or {"access_token": "a", "refresh_token": "r", "expires_in": 300}
        self.calls = []

    def __call__(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": parse_qs(data), "timeout": timeout})
        return _response(self.status, self.body, url)


KEYCLOAK = {
    "KEYCLOAK_HOST": "https://kc.invalid",
    "PROMPTSTORE_KEYCLOAK_REALM": "ps",
    "PROMPTSTORE_KEYCLOAK_CLIENT_ID": "cid",
    "PROMPTSTORE_KEYCLOAK_CLIENT_SECRET": "secret",
}


def test_keycloak_client_credentials_grant_is_synchronous(monkeypatch):
    kc = _Keycloak()
    monkeypatch.setattr("requests.post", kc)

    token = KeycloakAuth(KEYCLOAK).get_access_token()

    assert token["access_token"] == "a"
    call = kc.calls[0]
    assert call["url"] == "https://kc.invalid/realms/ps/protocol/openid-connect/token"
    assert call["data"] == {"client_id": ["cid"], "client_secret": ["secret"], "grant_type": ["client_credentials"]}
    assert call["timeout"] == 30


def test_keycloak_refresh_grant(monkeypatch):
    kc = _Keycloak()
    monkeypatch.setattr("requests.post", kc)

    KeycloakAuth(KEYCLOAK).refresh({"access_token": "a", "refresh_token": "r1"})

    assert kc.calls[0]["data"]["grant_type"] == ["refresh_token"]
    assert kc.calls[0]["data"]["refresh_token"] == ["r1"]


def test_keycloak_errors_propagate_as_request_exceptions(monkeypatch):
    monkeypatch.setattr("requests.post", _Keycloak(status=401))

    with pytest.raises(requests.HTTPError):
        KeycloakAuth(KEYCLOAK).get_access_token()


def test_keycloak_is_opt_in_with_auth_method_keycloak(monkeypatch, server):
    kc = _Keycloak(body={"access_token": "fresh", "refresh_token": "r"})
    monkeypatch.setattr("requests.post", kc)

    store = PromptStore({**KEYCLOAK, "AUTH_METHOD": "keycloak", "PROMPTSTORE_BASE_URL": "http://ps.invalid/api",
                         "WORKSPACE_ID": "1"})

    # before: the async grant was never awaited, so a coroutine was stored
    assert isinstance(store.auth, KeycloakAuth)
    assert store.api_service.get_access_token() == "fresh"
    store.api_service.get(URL)
    assert server.auth_headers == ["Bearer fresh"]


# ---- CognitoAuth ----

def _jwt(claims):
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'RS256', 'kid': 'k'})}.{part(claims)}.sig"


ID_TOKEN = _jwt({"email": "svc@example.com", "cognito:username": "3f2a-sub", "aud": "cid"})

COGNITO = {
    "PROMPTSTORE_COGNITO_REGION": "ap-southeast-2",
    "PROMPTSTORE_COGNITO_CLIENT_ID": "cid",
    "PROMPTSTORE_USERNAME": "svc@example.com",
    "PROMPTSTORE_PASSWORD": "pw",
}


class _Cognito:
    """Fakes cognito-idp InitiateAuth; records each request body."""

    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body
        self.calls = []

    def __call__(self, url, data=None, headers=None, timeout=None):
        request = json.loads(data)
        self.calls.append({"url": url, "headers": headers, "body": request, "timeout": timeout})
        if self.body is not None:
            return _response(self.status, self.body, url)
        result = {"IdToken": ID_TOKEN, "AccessToken": "cognito-access", "ExpiresIn": 3600}
        if request["AuthFlow"] == "USER_PASSWORD_AUTH":
            result["RefreshToken"] = "rt"
        return _response(self.status, {"AuthenticationResult": result}, url)


def _expected_secret_hash(username, client_id="cid", secret="s3cret"):
    digest = hmac.new(secret.encode(), (username + client_id).encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_cognito_signs_in_with_user_password_auth_and_returns_the_id_token(monkeypatch):
    cognito = _Cognito()
    monkeypatch.setattr("requests.post", cognito)

    token = CognitoAuth(COGNITO).get_access_token()

    # the server identifies callers by the ID token's email claim
    assert token["access_token"] == ID_TOKEN == token["id_token"]
    assert token["refresh_token"] == "rt"
    assert token["cognito_access_token"] == "cognito-access"
    call = cognito.calls[0]
    assert call["url"] == "https://cognito-idp.ap-southeast-2.amazonaws.com/"
    assert call["headers"]["X-Amz-Target"] == "AWSCognitoIdentityProviderService.InitiateAuth"
    assert call["headers"]["Content-Type"] == "application/x-amz-json-1.1"
    assert call["body"] == {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "ClientId": "cid",
        "AuthParameters": {"USERNAME": "svc@example.com", "PASSWORD": "pw"},
    }
    assert call["timeout"] == 30


def test_cognito_refresh_keeps_the_refresh_token(monkeypatch):
    cognito = _Cognito()
    monkeypatch.setattr("requests.post", cognito)

    token = CognitoAuth(COGNITO).refresh({"access_token": ID_TOKEN, "id_token": ID_TOKEN, "refresh_token": "rt"})

    assert cognito.calls[0]["body"]["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert cognito.calls[0]["body"]["AuthParameters"] == {"REFRESH_TOKEN": "rt"}
    assert token["refresh_token"] == "rt"  # Cognito sends no new one on refresh
    assert token["access_token"] == ID_TOKEN


def test_cognito_secret_hash_uses_the_sign_in_name_then_the_cognito_username(monkeypatch):
    cognito = _Cognito()
    monkeypatch.setattr("requests.post", cognito)
    auth = CognitoAuth({**COGNITO, "PROMPTSTORE_COGNITO_CLIENT_SECRET": "s3cret"})

    token = auth.get_access_token()
    auth.refresh(token)

    sign_in, refresh = (c["body"]["AuthParameters"]["SECRET_HASH"] for c in cognito.calls)
    assert sign_in == _expected_secret_hash("svc@example.com")
    assert refresh == _expected_secret_hash("3f2a-sub")


def test_cognito_challenge_is_an_explicit_error(monkeypatch):
    monkeypatch.setattr("requests.post",
                        _Cognito(body={"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "x"}))

    with pytest.raises(RuntimeError, match="NEW_PASSWORD_REQUIRED"):
        CognitoAuth(COGNITO).get_access_token()


def test_cognito_rejection_is_a_request_exception(monkeypatch, caplog):
    monkeypatch.setattr("requests.post", _Cognito(status=400, body={
        "__type": "com.amazonaws.cognito#NotAuthorizedException", "message": "Incorrect username or password.",
    }))

    with pytest.raises(requests.HTTPError):
        CognitoAuth(COGNITO).get_access_token()
    assert "NotAuthorizedException: Incorrect username or password." in caplog.text


def test_expired_refresh_token_falls_back_to_signing_in_again(monkeypatch, server):
    server.valid = ID_TOKEN

    def cognito(url, data=None, headers=None, timeout=None):
        if json.loads(data)["AuthFlow"] == "REFRESH_TOKEN_AUTH":
            return _response(400, {"__type": "NotAuthorizedException", "message": "Refresh Token has expired"}, url)
        return _Cognito()(url, data=data, headers=headers, timeout=timeout)

    monkeypatch.setattr("requests.post", cognito)
    api = ApiService(token_source=CognitoAuth(COGNITO))
    api.set_token({"access_token": "expired", "id_token": "expired", "refresh_token": "old"})

    api.get(URL)

    assert server.auth_headers == ["Bearer expired", f"Bearer {ID_TOKEN}"]


@pytest.mark.parametrize("method", ["cognito", "oauth", "COGNITO"])
def test_cognito_is_the_oauth_auth_method(monkeypatch, server, method):
    server.valid = ID_TOKEN
    monkeypatch.setattr("requests.post", _Cognito())

    store = PromptStore({**COGNITO, "AUTH_METHOD": method, "PROMPTSTORE_BASE_URL": "http://ps.invalid/api",
                         "WORKSPACE_ID": "1"})

    assert isinstance(store.auth, CognitoAuth)
    assert store.api_service.token_source is store.auth
    store.api_service.get(URL)
    assert server.auth_headers == [f"Bearer {ID_TOKEN}"]


def test_api_key_is_the_default_auth_method(monkeypatch):
    monkeypatch.delenv("AUTH_METHOD", raising=False)
    store = PromptStore({"PROMPTSTORE_BASE_URL": "http://ps.invalid/api", "WORKSPACE_ID": "1"})
    assert store.auth is None and store.api_service.token_source is None


def test_unknown_auth_method_is_rejected():
    with pytest.raises(ValueError, match="Unknown AUTH_METHOD 'cognitoo'"):
        PromptStore({"AUTH_METHOD": "cognitoo"})

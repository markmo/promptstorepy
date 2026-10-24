import base64
import hashlib
import hmac
import json
import logging
import os

import requests


class CognitoAuth:
    """Obtains PromptStore bearer tokens from an AWS Cognito user pool.

    Signs in a (service) user with ``USER_PASSWORD_AUTH`` and renews with
    ``REFRESH_TOKEN_AUTH``, calling Cognito's ``InitiateAuth`` API directly.

    The PromptStore server (``AUTH_PROVIDER=cognito``) identifies the caller
    from the token's ``email`` / ``cognito:username`` claims, which only the
    ID token carries, so ``access_token`` in the returned token is Cognito's
    **ID token**, the same token the PromptStore UI sends.

    The app client must be the one the server checks (its
    ``AWS_COGNITO_CLIENT_ID``) and must allow ``ALLOW_USER_PASSWORD_AUTH``
    and ``ALLOW_REFRESH_TOKEN_AUTH``. The user's Cognito groups become its
    PromptStore roles.

    Settings, from ``constants`` or the environment:
    ``PROMPTSTORE_COGNITO_REGION``, ``PROMPTSTORE_COGNITO_CLIENT_ID``,
    ``PROMPTSTORE_COGNITO_CLIENT_SECRET`` (only if the app client has one),
    ``PROMPTSTORE_USERNAME``, ``PROMPTSTORE_PASSWORD``.
    """

    def __init__(self, constants, logger=None, timeout=30):
        self.constants = constants or {}
        self.logger = logger or logging.getLogger(__name__)
        self.timeout = timeout

    def _setting(self, name):
        return self.constants.get(name, os.getenv(name))

    def _endpoint(self):
        return f"https://cognito-idp.{self._setting('PROMPTSTORE_COGNITO_REGION')}.amazonaws.com/"

    def _secret_hash(self, username):
        secret = self._setting("PROMPTSTORE_COGNITO_CLIENT_SECRET")
        if not secret:
            return None
        message = (username + self._setting("PROMPTSTORE_COGNITO_CLIENT_ID")).encode()
        return base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()

    def _initiate_auth(self, flow, parameters, username):
        secret_hash = self._secret_hash(username)
        if secret_hash:
            parameters = {**parameters, "SECRET_HASH": secret_hash}
        body = {
            "AuthFlow": flow,
            "ClientId": self._setting("PROMPTSTORE_COGNITO_CLIENT_ID"),
            "AuthParameters": parameters,
        }
        try:
            response = requests.post(self._endpoint(), data=json.dumps(body), headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            }, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as err:
            detail = _cognito_error(err.response)
            self.logger.error(f"Cognito {flow} failed: {detail or err}")
            raise
        data = response.json()
        result = data.get("AuthenticationResult")
        if not result:
            # e.g. NEW_PASSWORD_REQUIRED or an MFA challenge: needs a human,
            # so retrying cannot help.
            raise RuntimeError(
                f"Cognito {flow} returned the {data.get('ChallengeName')} challenge; "
                "a service user needs a confirmed password and no MFA"
            )
        return result

    @staticmethod
    def _token(result, refresh_token=None):
        return {
            "access_token": result["IdToken"],  # the bearer PromptStore expects (see class docstring)
            # REFRESH_TOKEN_AUTH returns no new refresh token: keep the old one
            "refresh_token": result.get("RefreshToken") or refresh_token,
            "id_token": result["IdToken"],
            "cognito_access_token": result.get("AccessToken"),
            "expires_in": result.get("ExpiresIn"),
        }

    def get_access_token(self):
        username = self._setting("PROMPTSTORE_USERNAME")
        result = self._initiate_auth("USER_PASSWORD_AUTH", {
            "USERNAME": username,
            "PASSWORD": self._setting("PROMPTSTORE_PASSWORD"),
        }, username)
        return self._token(result)

    def refresh(self, token):
        """Renew ``token`` (as returned by this class) with its refresh token."""
        refresh_token = token["refresh_token"]
        # With a client secret, the refresh SECRET_HASH must use the user's
        # Cognito username (often its sub), not the email it signed in with.
        username = _claim(token.get("id_token"), "cognito:username") or self._setting("PROMPTSTORE_USERNAME")
        result = self._initiate_auth("REFRESH_TOKEN_AUTH", {"REFRESH_TOKEN": refresh_token}, username)
        return self._token(result, refresh_token)


def _claim(jwt, name):
    """An unverified claim from a JWT's payload (the server verifies it)."""
    if not jwt:
        return None
    try:
        payload = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get(name)
    except (IndexError, ValueError):
        return None


def _cognito_error(response):
    """``__type: message`` from a Cognito error body, if it has one."""
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    kind = (body.get("__type") or "").split("#")[-1]
    return ": ".join(part for part in (kind, body.get("message")) if part) or None

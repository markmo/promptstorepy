import logging
import os
import threading
import requests

logger = logging.getLogger(__name__)


class ApiService:
    """HTTP client for the PromptStore API.

    Authenticates with a bearer token when one is set (``set_token``), else
    with the ``PROMPTSTORE_API_KEY`` header. With a ``token_source``, a 401
    renews the token once and retries the request once; a 403 is never
    retried, since a new token will not change it.

    A token source (``CognitoAuth``; ``KeycloakAuth`` for later) has
    ``get_access_token() -> token`` and ``refresh(token) -> token``, where a
    token is a dict whose ``access_token`` is the bearer to send and whose
    optional ``refresh_token`` renews it.
    """

    def __init__(self, token_source=None):
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.token_source = token_source
        self.state = None
        self.on_refresh_callback = None
        self.on_expiry_callback = None
        # Serializes renewal so threads that hit a 401 together refresh once.
        self._refresh_lock = threading.Lock()

    def set_token(self, token):
        self.state = token
        if callable(self.on_refresh_callback):
            self.on_refresh_callback(token)

    def on_refresh(self, callback):
        self.on_refresh_callback = callback

    def on_expiry(self, callback):
        self.on_expiry_callback = callback

    def get_access_token(self):
        return self.state.get("access_token") if self.state else None

    def get_refresh_token(self):
        return self.state.get("refresh_token") if self.state else None

    def renew_token(self):
        """Replace the current token: refresh grant if there is a refresh
        token, else (or if it is rejected) a fresh token from the source."""
        if self.token_source is None:
            raise RuntimeError("no token source configured to renew the access token")
        if self.get_refresh_token():
            try:
                self.set_token(self.token_source.refresh(self.state))
                return
            except requests.RequestException as err:
                logger.warning(f"token refresh failed, requesting a new token: {err}")
        self.set_token(self.token_source.get_access_token())

    def _send(self, method, url, kwargs):
        access_token = self.get_access_token()
        headers = dict(kwargs.get("headers") or {})
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        else:
            headers["apikey"] = os.getenv("PROMPTSTORE_API_KEY")
        headers.update(self.headers)
        logger.debug(f"url: {url} {kwargs}")
        response = requests.request(method, url, **{**kwargs, "headers": headers})
        logger.debug(f"response: {response}")
        return response, access_token

    def _renew_after_401(self, stale_token, response):
        with self._refresh_lock:
            if self.get_access_token() != stale_token:
                return  # another thread renewed it while this one waited
            try:
                self.renew_token()
            except Exception as err:
                if callable(self.on_expiry_callback):
                    self.on_expiry_callback(err)
                # Keep it a RequestException so callers' handlers still see
                # the original 401 response.
                raise requests.HTTPError(
                    f"401 Unauthorized for url: {response.url}; token renewal failed: {err}",
                    response=response,
                ) from err

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 120)
        response, used_token = self._send(method, url, kwargs)
        if response.status_code == 401 and used_token and self.token_source is not None:
            self._renew_after_401(used_token, response)
            response, _ = self._send(method, url, kwargs)
        if not response.ok:
            logger.error(f"{method} {url}: {response.status_code}")
        response.raise_for_status()
        return response

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


service = ApiService()

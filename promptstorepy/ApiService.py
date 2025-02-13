import asyncio
import logging
import os
import requests
from requests.exceptions import RequestException
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class ApiService:
    def __init__(self):
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.is_token_refreshing = False
        self.failed_queue = []
        self.state = None
        self.on_refresh_callback = None
        self.on_expiry_callback = None

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

    async def renew_token(self):
        refresh_token = self.get_refresh_token()
        token = await self.get_new_token(refresh_token)
        self.set_token(token)

    async def get_new_token(self, refresh_token):
        host = os.getenv("KEYCLOAK_HOST")
        realm = os.getenv("KEYCLOAK_REALM")
        url = f"{host}/realms/{realm}/protocol/openid-connect/token"
        client_id = os.getenv("KEYCLOAK_CLIENT_ID")
        client_secret = os.getenv("KEYCLOAK_CLIENT_SECRET")
        grant_type = "refresh_token"

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": grant_type,
            "refresh_token": refresh_token,
        }

        try:
            response = requests.post(
                url,
                data=urlencode(data),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            response.raise_for_status()
            res_data = response.json()
            return {
                "accessToken": res_data["access_token"],
                "refreshToken": res_data["refresh_token"],
            }
        except RequestException as err:
            message = f"Error getting new token: {err}"
            print(message)
            raise Exception(message)

    async def process_queue(self, error, access_token=None):
        for prom in self.failed_queue:
            if error:
                prom["reject"](error)
            else:
                prom["resolve"](access_token)
        self.failed_queue = []

    def request(self, method, url, **kwargs):
        access_token = self.get_access_token()
        headers = kwargs.pop("headers", {})
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        else:
            headers["apikey"] = os.getenv("PROMPTSTORE_API_KEY")

        headers.update(self.headers)
        kwargs["headers"] = headers

        try:
            logger.debug(f"url: {url} {kwargs}")
            response = requests.request(method, url, **kwargs, timeout=120)
            logger.debug(f"response: {response}")
            response.raise_for_status()
            return response
        except RequestException as err:
            logger.error(err)
            if err.response and err.response.status_code in [401, 403]:
                return self.handle_token_refresh(err, method, url, **kwargs)
            else:
                raise

    def handle_token_refresh(self, err, method, url, **kwargs):
        if self.is_token_refreshing:
            future = asyncio.Future()
            self.failed_queue.append(
                {"resolve": future.set_result, "reject": future.set_exception}
            )
            access_token = asyncio.run(future)
            kwargs["headers"]["Authorization"] = f"Bearer {access_token}"
            return self.request(method, url, **kwargs)

        self.is_token_refreshing = True
        original_request = err.request

        try:
            refresh_token = self.get_refresh_token()
            token = asyncio.run(self.get_new_token(refresh_token))
            self.set_token(token)
            kwargs["headers"]["Authorization"] = f'Bearer {token["accessToken"]}'
            response = self.request(method, url, **kwargs)
            self.process_queue(None, token["accessToken"])
            return response
        except Exception as err:
            self.process_queue(err)
            if callable(self.on_expiry_callback):
                self.on_expiry_callback(err)
            raise
        finally:
            self.is_token_refreshing = False

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


service = ApiService()

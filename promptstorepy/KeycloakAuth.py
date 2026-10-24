import os
import logging
import requests
from urllib.parse import urlencode


class KeycloakAuth:
    """Obtains PromptStore access tokens from Keycloak.

    Not used today: the PromptStore server verifies Cognito (and Firebase)
    bearer tokens only, so a Keycloak token is rejected with a 401. Kept for
    a future Keycloak-backed deployment; select it with
    ``AUTH_METHOD=keycloak``. The default token source is ``CognitoAuth``.

    ``get_access_token`` runs the client-credentials grant; ``refresh`` runs
    the refresh-token grant. Both return Keycloak's token response
    (``access_token``, and ``refresh_token`` when the realm issues one).
    """

    def __init__(self, constants, logger=None, timeout=30):
        self.constants = constants or {}
        self.logger = logger or logging.getLogger(__name__)
        self.timeout = timeout

    def _setting(self, name):
        return self.constants.get(name, os.getenv(name))

    def _token_url(self):
        host = self._setting('KEYCLOAK_HOST')
        realm = self._setting('PROMPTSTORE_KEYCLOAK_REALM')
        return f'{host}/realms/{realm}/protocol/openid-connect/token'

    def _grant(self, grant_type, **extra):
        data = {
            'client_id': self._setting('PROMPTSTORE_KEYCLOAK_CLIENT_ID'),
            'client_secret': self._setting('PROMPTSTORE_KEYCLOAK_CLIENT_SECRET'),
            'grant_type': grant_type,
            **extra,
        }
        try:
            response = requests.post(self._token_url(), data=urlencode(data), headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            }, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as err:
            self.logger.error(f'Keycloak {grant_type} grant failed: {err}')
            raise

    def get_access_token(self):
        return self._grant('client_credentials')

    def refresh(self, token):
        return self._grant('refresh_token', refresh_token=token['refresh_token'])

# Usage example:
# constants = {
#     'KEYCLOAK_HOST': 'https://keycloak.example.com',
#     'PROMPTSTORE_KEYCLOAK_REALM': 'myrealm',
#     'PROMPTSTORE_KEYCLOAK_CLIENT_ID': 'myclientid',
#     'PROMPTSTORE_KEYCLOAK_CLIENT_SECRET': 'myclientsecret',
# }
# logger = logging.getLogger('keycloak_auth')
# keycloak_auth = KeycloakAuth(constants, logger)
# token = keycloak_auth.get_access_token()

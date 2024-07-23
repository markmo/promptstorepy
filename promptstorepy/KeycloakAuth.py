import os
import logging
import requests
from urllib.parse import urlencode


class KeycloakAuth:

    def __init__(self, constants, logger=None):
        self.constants = constants
        self.logger = logger or logging.getLogger(__name__)

    async def get_access_token(self):
        host = self.constants.get('KEYCLOAK_HOST', os.getenv('KEYCLOAK_HOST'))
        realm = self.constants.get('PROMPTSTORE_KEYCLOAK_REALM', os.getenv('PROMPTSTORE_KEYCLOAK_REALM'))
        client_id = self.constants.get('PROMPTSTORE_KEYCLOAK_CLIENT_ID', os.getenv('PROMPTSTORE_KEYCLOAK_CLIENT_ID'))
        client_secret = self.constants.get('PROMPTSTORE_KEYCLOAK_CLIENT_SECRET', os.getenv('PROMPTSTORE_KEYCLOAK_CLIENT_SECRET'))
        url = f'{host}/realms/{realm}/protocol/openid-connect/token'
        grant_type = 'client_credentials'

        # self.logger.debug(f"curl -vL -H 'Content-Type: application/x-www-form-urlencoded' {url} -d 'client_id={client_id}&client_secret={client_secret}&grant_type={grant_type}'")

        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': grant_type,
        }
        try:
            response = requests.post(url, data=urlencode(data), headers={
                'Content-Type': 'application/x-www-form-urlencoded',
            })
            response.raise_for_status()
            return response.json()
        except requests.RequestException as err:
            self.logger.error(err, exc_info=True)
            raise

# Usage example:
# constants = {
#     'KEYCLOAK_HOST': 'https://keycloak.example.com',
#     'PROMPTSTORE_KEYCLOAK_REALM': 'myrealm',
#     'PROMPTSTORE_KEYCLOAK_CLIENT_ID': 'myclientid',
#     'PROMPTSTORE_KEYCLOAK_CLIENT_SECRET': 'myclientsecret',
# }
# logger = logging.getLogger('keycloak_auth')
# keycloak_auth = KeycloakAuth(constants, logger)
# access_token = asyncio.run(keycloak_auth.get_access_token())

# promptstorepy

Python client for the PromptStore API.

## Authentication

Set `AUTH_METHOD` (in `constants` or the environment):

| `AUTH_METHOD` | How requests authenticate |
|---|---|
| unset or `apikey` | `apikey` header from `PROMPTSTORE_API_KEY` |
| `cognito` (alias `oauth`) | Bearer token from the AWS Cognito user pool the server verifies |
| `keycloak` | Not supported by the server yet; kept for a future Keycloak deployment |

### Cognito

The client signs in a service user with `USER_PASSWORD_AUTH` and sends its
**ID token**, the token the PromptStore UI sends. The server identifies callers
by the token's `email` claim, and turns the user's Cognito groups into its
PromptStore roles. When the server answers 401, the client renews the token once
(refresh token, or a fresh sign-in if that has expired) and retries once.

| Setting | Value |
|---|---|
| `PROMPTSTORE_COGNITO_REGION` | The user pool's region |
| `PROMPTSTORE_COGNITO_CLIENT_ID` | The app client the server checks: the same value as its `AWS_COGNITO_CLIENT_ID` |
| `PROMPTSTORE_COGNITO_CLIENT_SECRET` | Only if that app client has a secret |
| `PROMPTSTORE_USERNAME` / `PROMPTSTORE_PASSWORD` | The service user |

The app client must allow `ALLOW_USER_PASSWORD_AUTH` and
`ALLOW_REFRESH_TOKEN_AUTH`. The user needs a confirmed password and no MFA; a
Cognito challenge raises `RuntimeError`. The server must run with
`AUTH_PROVIDER=cognito`.

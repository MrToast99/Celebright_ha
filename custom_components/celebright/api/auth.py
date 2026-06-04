"""AWS Cognito authentication for Celebright.

Uses USER_PASSWORD_AUTH flow (simpler than SRP) — requires this flow to be
enabled on the Celebright Cognito User Pool. If it's disabled, switch to
USER_SRP_AUTH by using the `warrant` or `pycognito` library.

Token refresh is handled automatically: when the 1-hour access token expires,
the refresh token (valid for 30 days) is used to obtain new tokens.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

from .base import CelebrightAuthError, CelebrightConnectionError
from ..const import (
    AWS_REGION,
    COGNITO_CLIENT_ID,
    COGNITO_IDENTITY_ENDPOINT,
    COGNITO_IDENTITY_POOL_ID,
    COGNITO_IDP_ENDPOINT,
    COGNITO_USER_POOL_ID,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class CognitoTokens:
    id_token: str
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds


@dataclass
class AWSCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expiration: float  # epoch seconds
    identity_id: str


class CelebrightAuth:
    """Handles Cognito auth and temporary AWS credential exchange."""

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession) -> None:
        self._email = email
        self._password = password
        self._session = session
        self._tokens: CognitoTokens | None = None
        self._credentials: AWSCredentials | None = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def async_authenticate(self) -> None:
        """Full auth flow: Cognito login → identity credentials."""
        self._tokens = await self._cognito_login()
        self._credentials = await self._get_aws_credentials(self._tokens)

    async def async_ensure_valid(self) -> None:
        """Refresh tokens and/or credentials if they are about to expire."""
        now = time.time()

        if self._tokens is None or now >= self._tokens.expires_at - 60:
            if self._tokens and self._tokens.refresh_token:
                try:
                    self._tokens = await self._cognito_refresh(self._tokens.refresh_token)
                except CelebrightAuthError:
                    _LOGGER.warning("Token refresh failed, re-authenticating")
                    await self.async_authenticate()
                    return
            else:
                await self.async_authenticate()
                return

        if self._credentials is None or now >= self._credentials.expiration - 300:
            self._credentials = await self._get_aws_credentials(self._tokens)

    @property
    def id_token(self) -> str:
        assert self._tokens, "Not authenticated"
        return self._tokens.id_token

    @property
    def aws_credentials(self) -> AWSCredentials:
        assert self._credentials, "Not authenticated"
        return self._credentials

    # ------------------------------------------------------------------
    # Cognito login
    # ------------------------------------------------------------------

    async def _cognito_login(self) -> CognitoTokens:
        payload = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": COGNITO_CLIENT_ID,
            "AuthParameters": {
                "USERNAME": self._email,
                "PASSWORD": self._password,
            },
        }
        body = await self._cognito_idp_call(
            "AWSCognitoIdentityProviderService.InitiateAuth", payload
        )
        result = body.get("AuthenticationResult", {})
        if not result.get("IdToken"):
            raise CelebrightAuthError("USER_PASSWORD_AUTH not enabled on this pool; SRP flow required")
        return _parse_tokens(result)

    async def _cognito_refresh(self, refresh_token: str) -> CognitoTokens:
        payload = {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": COGNITO_CLIENT_ID,
            "AuthParameters": {"REFRESH_TOKEN": refresh_token},
        }
        body = await self._cognito_idp_call(
            "AWSCognitoIdentityProviderService.InitiateAuth", payload
        )
        result = body.get("AuthenticationResult", {})
        if not result.get("IdToken"):
            raise CelebrightAuthError("Token refresh failed")
        tokens = _parse_tokens(result)
        # Refresh flow does not return a new refresh token
        tokens.refresh_token = refresh_token
        return tokens

    # ------------------------------------------------------------------
    # Identity credentials exchange
    # ------------------------------------------------------------------

    async def _get_aws_credentials(self, tokens: CognitoTokens) -> AWSCredentials:
        login_key = f"cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"

        # Step 1: GetId
        get_id_body = await self._cognito_identity_call(
            "AWSCognitoIdentityService.GetId",
            {
                "IdentityPoolId": COGNITO_IDENTITY_POOL_ID,
                "Logins": {login_key: tokens.id_token},
            },
        )
        identity_id: str = get_id_body["IdentityId"]

        # Step 2: GetCredentialsForIdentity
        creds_body = await self._cognito_identity_call(
            "AWSCognitoIdentityService.GetCredentialsForIdentity",
            {
                "IdentityId": identity_id,
                "Logins": {login_key: tokens.id_token},
            },
        )
        creds = creds_body["Credentials"]
        expiration = creds.get("Expiration", time.time() + 3600)
        if isinstance(expiration, str):
            import datetime
            dt = datetime.datetime.fromisoformat(expiration.replace("Z", "+00:00"))
            expiration = dt.timestamp()

        return AWSCredentials(
            access_key_id=creds["AccessKeyId"],
            secret_access_key=creds["SecretKey"],
            session_token=creds["SessionToken"],
            expiration=expiration,
            identity_id=identity_id,
        )

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _cognito_idp_call(self, target: str, payload: dict) -> dict:
        return await self._amz_post(
            COGNITO_IDP_ENDPOINT,
            target,
            payload,
            content_type="application/x-amz-json-1.1",
        )

    async def _cognito_identity_call(self, target: str, payload: dict) -> dict:
        return await self._amz_post(
            COGNITO_IDENTITY_ENDPOINT,
            target,
            payload,
            content_type="application/x-amz-json-1.1",
        )

    async def _amz_post(
        self, url: str, target: str, payload: dict, content_type: str
    ) -> dict:
        headers = {
            "Content-Type": content_type,
            "X-Amz-Target": target,
            "Cache-Control": "no-store",
        }
        try:
            async with asyncio.timeout(15):
                resp = await self._session.post(url, json=payload, headers=headers)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CelebrightConnectionError(f"Cognito request failed: {err}") from err

        if resp.status == 400:
            body = await resp.json(content_type=None)
            code = body.get("__type", "")
            msg = body.get("message", str(body))
            if "NotAuthorized" in code or "UserNotFound" in code:
                raise CelebrightAuthError(msg)
            raise CelebrightConnectionError(f"Cognito 400 {code}: {msg}")
        if resp.status != 200:
            text = await resp.text()
            raise CelebrightConnectionError(f"Cognito HTTP {resp.status}: {text}")

        return await resp.json(content_type=None)


def _parse_tokens(result: dict) -> CognitoTokens:
    expires_in: int = result.get("ExpiresIn", 3600)
    return CognitoTokens(
        id_token=result["IdToken"],
        access_token=result["AccessToken"],
        refresh_token=result.get("RefreshToken", ""),
        expires_at=time.time() + expires_in,
    )

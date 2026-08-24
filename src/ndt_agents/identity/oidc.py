"""Offline OIDC JWT verification against an explicitly supplied JWKS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import jwt
from pydantic import ValidationError

from ndt_agents.identity.models import IdentityError, OidcSettings, Principal


class OidcJwtVerifier:
    """Verify signed bearer tokens without hidden discovery or JWKS network calls."""

    def __init__(self, *, settings: OidcSettings, jwks: Mapping[str, Any]) -> None:
        self._settings = settings
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("JWKS must contain at least one key")
        parsed: dict[str, Mapping[str, Any]] = {}
        for candidate in keys:
            if not isinstance(candidate, Mapping):
                raise ValueError("JWKS key must be an object")
            kid = candidate.get("kid")
            algorithm = candidate.get("alg")
            usage = candidate.get("use", "sig")
            if not isinstance(kid, str) or not kid or kid in parsed:
                raise ValueError("JWKS key IDs must be present and unique")
            if algorithm not in settings.allowed_algorithms or usage != "sig":
                continue
            parsed[kid] = candidate
        if not parsed:
            raise ValueError("JWKS has no allowed signing key")
        self._keys = parsed

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise self._invalid_token() from None
        algorithm = header.get("alg")
        key_id = header.get("kid")
        token_type = header.get("typ")
        if algorithm not in self._settings.allowed_algorithms or token_type not in {None, "JWT"}:
            raise self._invalid_token()
        if not isinstance(key_id, str) or key_id not in self._keys:
            raise IdentityError(
                code="AUTH_KEY_UNKNOWN",
                status_code=401,
                message="The authentication signing key is not recognized.",
                next_action="Refresh authentication through the approved identity provider.",
            )
        try:
            signing_key = jwt.PyJWK.from_dict(dict(self._keys[key_id]), algorithm=algorithm).key
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=list(self._settings.allowed_algorithms),
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.clock_skew_seconds,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "user_id",
                        "tenant_id",
                        "project_ids",
                        "roles",
                        "permission_version",
                        "iat",
                        "nbf",
                        "exp",
                        "jti",
                    ]
                },
            )
        except jwt.ExpiredSignatureError:
            raise IdentityError(
                code="AUTH_TOKEN_EXPIRED",
                status_code=401,
                message="The authentication credential has expired.",
                next_action="Authenticate again through the approved identity provider.",
            ) from None
        except jwt.PyJWTError:
            raise self._invalid_token() from None
        try:
            return Principal(
                subject=claims["sub"],
                user_id=claims["user_id"],
                tenant_id=claims["tenant_id"],
                project_ids=tuple(claims["project_ids"]),
                roles=tuple(claims["roles"]),
                permission_version=claims["permission_version"],
                token_id=claims["jti"],
            )
        except (KeyError, TypeError, ValidationError):
            raise self._invalid_token() from None

    @staticmethod
    def _invalid_token() -> IdentityError:
        return IdentityError(
            code="AUTH_TOKEN_INVALID",
            status_code=401,
            message="The authentication credential is invalid.",
            next_action="Authenticate again through the approved identity provider.",
        )

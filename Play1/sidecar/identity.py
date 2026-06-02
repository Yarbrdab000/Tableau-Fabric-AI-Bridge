"""Caller identity extraction, Entra -> Tableau username mapping, Connected App JWT
sign-in, and a strict-keyed per-user session-token cache.

All Connected App JWT logic is HS256 via the standard library (no extra crypto deps),
matching the repo's live-tested ``build_connected_app_jwt`` in the profiler skill.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import httpx

from config import SidecarConfig

JWT_MAX_TTL_SECONDS = 600


class IdentityError(RuntimeError):
    """Caller identity could not be resolved to a Tableau user (fail-closed)."""


class UpstreamAuthError(RuntimeError):
    """Tableau rejected the per-user Connected App sign-in."""


@dataclass(frozen=True)
class CallerIdentity:
    """The validated Entra identity of the caller (from Easy Auth / APIM)."""

    upn: str
    object_id: Optional[str]
    tenant_id: Optional[str]


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_connected_app_jwt(
    client_id: str,
    secret_id: str,
    secret_value: str,
    username: str,
    scopes: list,
    ttl_seconds: int = 300,
) -> str:
    """Signed HS256 JWT for Tableau Connected App (Direct Trust) sign-in as ``username``."""
    if not all([client_id, secret_id, secret_value, username]):
        raise IdentityError(
            "Connected App JWT requires client_id, secret_id, secret_value, and username."
        )
    ttl = max(1, min(int(ttl_seconds), JWT_MAX_TTL_SECONDS))
    header = {"alg": "HS256", "kid": secret_id, "iss": client_id}
    now = int(time.time())
    payload = {
        "iss": client_id,
        "aud": "tableau",
        "sub": username,
        "scp": list(scopes),
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    signature = hmac.new(
        secret_value.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return signing_input + "." + _b64url(signature)


def _decode_principal_blob(blob: str) -> Dict[str, str]:
    """Decode the base64 X-MS-CLIENT-PRINCIPAL JSON into a flat {claim_type: value} map.

    Easy Auth emits a structure like {"claims":[{"typ":"...","val":"..."}], ...}. We index
    the last value per claim type. Returns {} if the blob is unparseable.
    """
    try:
        padded = blob + "=" * (-len(blob) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
        data = json.loads(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}
    out: Dict[str, str] = {}
    for claim in data.get("claims", []) or []:
        typ = claim.get("typ")
        val = claim.get("val")
        if typ and val is not None:
            out[str(typ)] = str(val)
    return out


# Common Entra claim URIs that carry the UPN / email / tenant / object id.
_UPN_CLAIMS = (
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
    "preferred_username",
    "upn",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "email",
)
_TENANT_CLAIMS = ("http://schemas.microsoft.com/identity/claims/tenantid", "tid")
_OID_CLAIMS = ("http://schemas.microsoft.com/identity/claims/objectidentifier", "oid")


def extract_caller_identity(headers) -> Optional[CallerIdentity]:
    """Read the Entra identity from trusted Easy Auth / APIM headers.

    ``headers`` is a mapping (case-insensitive, e.g. Starlette Headers) that the proxy has
    already STRIPPED of any client-supplied identity headers — so what remains was set by
    the platform/gateway in front of us. Returns None if no Entra identity is present.
    """
    # Simplest + most reliable: Easy Auth sets the UPN directly.
    name = headers.get("x-ms-client-principal-name")
    object_id = headers.get("x-ms-client-principal-id")
    tenant_id = None

    blob = headers.get("x-ms-client-principal")
    if blob:
        claims = _decode_principal_blob(blob)
        if not name:
            for c in _UPN_CLAIMS:
                if claims.get(c):
                    name = claims[c]
                    break
        if not object_id:
            for c in _OID_CLAIMS:
                if claims.get(c):
                    object_id = claims[c]
                    break
        for c in _TENANT_CLAIMS:
            if claims.get(c):
                tenant_id = claims[c]
                break

    if not name:
        return None
    return CallerIdentity(
        upn=name.strip(),
        object_id=object_id.strip() if object_id else None,
        tenant_id=tenant_id.strip() if tenant_id else None,
    )


def map_upn_to_tableau_username(upn: str, config: SidecarConfig) -> str:
    """Map an Entra UPN to a Tableau username per the configured strategy. Fail-closed."""
    upn_norm = upn.strip()
    if not upn_norm:
        raise IdentityError("Empty UPN; cannot resolve a Tableau identity.")

    mode = config.upn_mapping_mode
    if mode == "direct":
        return upn_norm
    if mode == "transform":
        local, _, domain = upn_norm.partition("@")
        if domain.lower() == (config.upn_domain_from or "").lower():
            return f"{local}@{config.upn_domain_to}"
        # Domain doesn't match the configured source domain -> not mappable -> deny.
        raise IdentityError(
            f"UPN domain {domain!r} is not the configured source domain; identity not mappable."
        )
    if mode == "explicit":
        mapped = config.upn_explicit_map.get(upn_norm.lower())
        if not mapped:
            raise IdentityError(f"No explicit Tableau mapping for UPN {upn_norm!r}.")
        return mapped
    raise IdentityError(f"Unknown UPN mapping mode {mode!r}.")


@dataclass
class _CacheEntry:
    token: str
    expires_at: float


class TokenCache:
    """In-memory, thread-safe cache of per-user Tableau session tokens.

    Keyed by the full identity tuple (server, site, mapped username, tenant, object id,
    identity mode, connected-app client id) — NOT the UPN alone — so a renamed/reused UPN
    or a cross-tenant collision can never reuse another user's token. Tokens are never
    logged or persisted.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = max(1, int(ttl_seconds))
        self._lock = threading.Lock()
        self._store: Dict[Tuple, _CacheEntry] = {}

    def get(self, key: Tuple) -> Optional[str]:
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if entry.expires_at <= now:
                self._store.pop(key, None)
                return None
            return entry.token

    def set(self, key: Tuple, token: str) -> None:
        with self._lock:
            self._store[key] = _CacheEntry(token=token, expires_at=time.time() + self._ttl)

    def evict(self, key: Tuple) -> None:
        with self._lock:
            self._store.pop(key, None)


def cache_key(config: SidecarConfig, caller: CallerIdentity, tableau_username: str) -> Tuple:
    return (
        config.tableau_server,
        config.tableau_site,
        tableau_username,
        caller.tenant_id or config.entra_tenant_id,
        caller.object_id,
        config.identity_mode,
        config.connected_app_client_id,
    )


async def tableau_signin_as(
    client: httpx.AsyncClient, config: SidecarConfig, tableau_username: str
) -> str:
    """Sign in to Tableau REST as ``tableau_username`` via Connected App JWT. Returns the
    ``X-Tableau-Auth`` session token. Raises UpstreamAuthError on rejection."""
    jwt = build_connected_app_jwt(
        config.connected_app_client_id,
        config.connected_app_secret_id,
        config.connected_app_secret_value,
        tableau_username,
        config.jwt_scopes,
    )
    body = {
        "credentials": {
            "jwt": jwt,
            "site": {"contentUrl": config.tableau_site},
        }
    }
    url = f"{config.tableau_server}/api/{config.tableau_rest_version}/auth/signin"
    try:
        resp = await client.post(
            url,
            content=json.dumps(body),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise UpstreamAuthError(f"Tableau sign-in request failed: {exc}") from exc
    if resp.status_code != 200:
        # Do not echo the response body verbatim (may contain detail); keep it terse.
        raise UpstreamAuthError(
            f"Tableau sign-in as {tableau_username!r} failed (HTTP {resp.status_code})."
        )
    try:
        return resp.json()["credentials"]["token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamAuthError("Unexpected Tableau sign-in response shape.") from exc


async def resolve_tableau_token(
    client: httpx.AsyncClient,
    config: SidecarConfig,
    caller: CallerIdentity,
    cache: TokenCache,
) -> Tuple[str, Tuple]:
    """Resolve (and cache) an X-Tableau-Auth token for the caller. Returns (token, key).

    Raises IdentityError if the UPN cannot be mapped, UpstreamAuthError if Tableau rejects
    the per-user sign-in. Either way the caller of this function must fail closed.
    """
    tableau_username = map_upn_to_tableau_username(caller.upn, config)
    key = cache_key(config, caller, tableau_username)
    cached = cache.get(key)
    if cached:
        return cached, key
    token = await tableau_signin_as(client, config, tableau_username)
    cache.set(key, token)
    return token, key

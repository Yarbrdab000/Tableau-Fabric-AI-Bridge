"""Sidecar configuration + startup validation.

The sidecar is the public ingress in front of the OFFICIAL Tableau MCP server. It does
two jobs:

  1. Authenticate the *caller* (the Copilot Studio / M365 / Foundry agent) using either a
     shared ``x-api-key`` (demo fallback) or a Microsoft Entra identity that an upstream
     gateway (Container Apps Easy Auth, or APIM) already validated.
  2. Decide which Tableau identity the request runs as:
       * ``service_account`` (default) — no per-user identity. The official server holds
         its own Tableau credentials (PAT / static direct-trust) and the sidecar simply
         proxies. RLS is whatever the service account sees.
       * ``passthrough`` — map the caller's Entra UPN to a Tableau username, sign a
         Connected App (direct-trust) JWT as that user, exchange it for a Tableau session
         token, and inject it as ``X-Tableau-Auth`` so Tableau row-level security applies
         per signed-in user.

The two identity modes are mutually exclusive and resolved once, at startup.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Connected App JWT scopes requested at per-user sign-in. Superset of what the official
# tools need (content read, VizQL Data Service, Pulse). Tableau ignores unused scopes.
DEFAULT_JWT_SCOPES: List[str] = [
    "tableau:content:read",
    "tableau:viz_data_service:read",
    "tableau:insight_definitions_metrics:read",
    "tableau:insight_metrics:read",
    "tableau:metric_subscriptions:read",
    "tableau:insights:read",
]

# Headers a client must never be able to set themselves — the sidecar strips these from
# every inbound request before adding its own trusted values.
SPOOFABLE_INBOUND_HEADERS: List[str] = [
    "x-tableau-auth",
    "x-ms-client-principal",
    "x-ms-client-principal-name",
    "x-ms-client-principal-id",
    "x-ms-client-principal-idp",
    "x-upn",
    "x-user",
]

# Hop-by-hop headers (RFC 7230 6.1) that must not be forwarded by a proxy.
HOP_BY_HOP_HEADERS: List[str] = [
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
]


class ConfigError(RuntimeError):
    """Raised when the sidecar is misconfigured. Fails the process at startup."""


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class SidecarConfig:
    # Networking
    port: int
    upstream_mcp_url: str
    upstream_request_timeout_s: float

    # Caller auth (how the agent authenticates TO the sidecar)
    allow_api_key: bool
    api_key: Optional[str]
    trust_easy_auth: bool

    # Identity mode (how the request runs AS a Tableau user)
    identity_mode: str  # "service_account" | "passthrough"
    on_unresolved_identity: str  # "deny"

    # Tableau / Connected App (passthrough only)
    tableau_server: Optional[str]
    tableau_site: str
    tableau_rest_version: str
    connected_app_client_id: Optional[str]
    connected_app_secret_id: Optional[str]
    connected_app_secret_value: Optional[str]
    jwt_scopes: List[str]

    # Entra -> Tableau username mapping (passthrough only)
    upn_mapping_mode: str  # "direct" | "transform" | "explicit"
    upn_domain_from: Optional[str]
    upn_domain_to: Optional[str]
    upn_explicit_map: Dict[str, str] = field(default_factory=dict)
    entra_tenant_id: Optional[str] = None

    # Per-user session-token cache
    token_cache_ttl_s: int = 1800

    @property
    def is_passthrough(self) -> bool:
        return self.identity_mode == "passthrough"

    def public_diagnostics(self) -> Dict[str, object]:
        """Non-secret view of the config for /healthz."""
        return {
            "identity_mode": self.identity_mode,
            "on_unresolved_identity": self.on_unresolved_identity,
            "caller_auth": {
                "api_key": self.allow_api_key,
                "easy_auth": self.trust_easy_auth,
            },
            "upstream_mcp_url": self.upstream_mcp_url,
            "tableau_server": self.tableau_server,
            "tableau_site": self.tableau_site or "(default)",
            "upn_mapping_mode": self.upn_mapping_mode if self.is_passthrough else None,
            "token_cache_ttl_s": self.token_cache_ttl_s if self.is_passthrough else None,
        }


def _load_explicit_map() -> Dict[str, str]:
    raw = _env("UPN_MAP_JSON")
    path = _env("UPN_MAP_PATH")
    if raw and path:
        raise ConfigError("Set only one of UPN_MAP_JSON or UPN_MAP_PATH, not both.")
    text: Optional[str] = raw
    if path:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"UPN_MAP_PATH does not exist: {path}")
        text = p.read_text(encoding="utf-8")
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"UPN mapping is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("UPN mapping JSON must be an object of {upn: tableau_username}.")
    # Normalize keys to lowercase for case-insensitive UPN lookup.
    return {str(k).strip().lower(): str(v).strip() for k, v in data.items()}


def load_config() -> SidecarConfig:
    """Build + validate the config from the environment. Raises ConfigError on misuse."""
    identity_mode = (_env("IDENTITY_MODE", "service_account") or "").strip().lower()
    if identity_mode not in ("service_account", "passthrough"):
        raise ConfigError(
            f"IDENTITY_MODE must be 'service_account' or 'passthrough', got {identity_mode!r}"
        )

    on_unresolved = (_env("ON_UNRESOLVED_IDENTITY", "deny") or "").strip().lower()
    if on_unresolved != "deny":
        # Only fail-closed is supported today. A future least_privilege / service_account
        # fallback would be an explicit, documented opt-in.
        raise ConfigError(
            "ON_UNRESOLVED_IDENTITY only supports 'deny' (fail-closed) in this version."
        )

    allow_api_key = _env_bool("ALLOW_API_KEY", default=True)
    api_key = _env("SIDECAR_API_KEY")
    trust_easy_auth = _env_bool("TRUST_EASY_AUTH", default=False)

    if allow_api_key and not api_key:
        raise ConfigError(
            "ALLOW_API_KEY is true but SIDECAR_API_KEY is not set. Set the key or disable api-key auth."
        )
    if not allow_api_key and not trust_easy_auth:
        raise ConfigError(
            "No caller authentication enabled. Enable ALLOW_API_KEY (+SIDECAR_API_KEY) and/or TRUST_EASY_AUTH."
        )

    upn_mapping_mode = (_env("UPN_MAPPING_MODE", "direct") or "").strip().lower()
    upn_domain_from = _env("UPN_DOMAIN_FROM")
    upn_domain_to = _env("UPN_DOMAIN_TO")
    explicit_map: Dict[str, str] = {}

    tableau_server = _env("TABLEAU_SERVER")
    connected_app_client_id = _env("TABLEAU_CONNECTED_APP_CLIENT_ID")
    connected_app_secret_id = _env("TABLEAU_CONNECTED_APP_SECRET_ID")
    connected_app_secret_value = _env("TABLEAU_CONNECTED_APP_SECRET_VALUE")

    if identity_mode == "passthrough":
        if upn_mapping_mode not in ("direct", "transform", "explicit"):
            raise ConfigError(
                f"UPN_MAPPING_MODE must be direct|transform|explicit, got {upn_mapping_mode!r}"
            )
        if upn_mapping_mode == "transform":
            if not (upn_domain_from and upn_domain_to):
                raise ConfigError(
                    "UPN_MAPPING_MODE=transform requires UPN_DOMAIN_FROM and UPN_DOMAIN_TO."
                )
        if upn_mapping_mode == "explicit":
            explicit_map = _load_explicit_map()
            if not explicit_map:
                raise ConfigError(
                    "UPN_MAPPING_MODE=explicit requires UPN_MAP_JSON or UPN_MAP_PATH with at least one entry."
                )
        missing = [
            n
            for n, v in (
                ("TABLEAU_SERVER", tableau_server),
                ("TABLEAU_CONNECTED_APP_CLIENT_ID", connected_app_client_id),
                ("TABLEAU_CONNECTED_APP_SECRET_ID", connected_app_secret_id),
                ("TABLEAU_CONNECTED_APP_SECRET_VALUE", connected_app_secret_value),
            )
            if not v
        ]
        if missing:
            raise ConfigError(
                "IDENTITY_MODE=passthrough requires Connected App settings; missing: "
                + ", ".join(missing)
            )
        if not trust_easy_auth:
            raise ConfigError(
                "IDENTITY_MODE=passthrough needs an Entra identity; set TRUST_EASY_AUTH=true "
                "(Easy Auth / APIM in front) so the caller's UPN is available."
            )

    scopes_env = _env("TABLEAU_JWT_SCOPES")
    jwt_scopes = (
        [s.strip() for s in scopes_env.split(",") if s.strip()]
        if scopes_env
        else list(DEFAULT_JWT_SCOPES)
    )

    return SidecarConfig(
        port=_env_int("PORT", 9000),
        upstream_mcp_url=_env("UPSTREAM_MCP_URL", "http://localhost:8000/mcp"),
        upstream_request_timeout_s=float(_env("UPSTREAM_REQUEST_TIMEOUT_S", "600")),
        allow_api_key=allow_api_key,
        api_key=api_key,
        trust_easy_auth=trust_easy_auth,
        identity_mode=identity_mode,
        on_unresolved_identity=on_unresolved,
        tableau_server=tableau_server.rstrip("/") if tableau_server else None,
        tableau_site=_env("TABLEAU_SITE", "") or "",
        tableau_rest_version=_env("TABLEAU_REST_VERSION", "3.21"),
        connected_app_client_id=connected_app_client_id,
        connected_app_secret_id=connected_app_secret_id,
        connected_app_secret_value=connected_app_secret_value,
        jwt_scopes=jwt_scopes,
        upn_mapping_mode=upn_mapping_mode,
        upn_domain_from=upn_domain_from,
        upn_domain_to=upn_domain_to,
        upn_explicit_map=explicit_map,
        entra_tenant_id=_env("ENTRA_TENANT_ID"),
        token_cache_ttl_s=_env_int("TOKEN_CACHE_TTL_S", 1800),
    )

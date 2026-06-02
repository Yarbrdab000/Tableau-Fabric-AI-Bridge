"""Startup config validation tests."""

import pytest

import config as config_mod
from config import ConfigError, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # Wipe every env var the loader reads so each test starts from a known baseline.
    for var in (
        "IDENTITY_MODE", "ON_UNRESOLVED_IDENTITY", "ALLOW_API_KEY", "SIDECAR_API_KEY",
        "TRUST_EASY_AUTH", "UPN_MAPPING_MODE", "UPN_DOMAIN_FROM", "UPN_DOMAIN_TO",
        "UPN_MAP_JSON", "UPN_MAP_PATH", "TABLEAU_SERVER", "TABLEAU_SITE",
        "TABLEAU_CONNECTED_APP_CLIENT_ID", "TABLEAU_CONNECTED_APP_SECRET_ID",
        "TABLEAU_CONNECTED_APP_SECRET_VALUE", "TABLEAU_JWT_SCOPES", "ENTRA_TENANT_ID",
        "PORT", "UPSTREAM_MCP_URL", "UPSTREAM_REQUEST_TIMEOUT_S", "TOKEN_CACHE_TTL_S",
        "TABLEAU_REST_VERSION",
    ):
        monkeypatch.delenv(var, raising=False)


def test_default_service_account_requires_api_key(monkeypatch):
    with pytest.raises(ConfigError):
        load_config()  # ALLOW_API_KEY defaults true but no SIDECAR_API_KEY set


def test_service_account_minimal_ok(monkeypatch):
    monkeypatch.setenv("SIDECAR_API_KEY", "k")
    cfg = load_config()
    assert cfg.identity_mode == "service_account"
    assert cfg.allow_api_key and not cfg.trust_easy_auth


def test_no_caller_auth_at_all_fails(monkeypatch):
    monkeypatch.setenv("ALLOW_API_KEY", "false")
    monkeypatch.setenv("TRUST_EASY_AUTH", "false")
    with pytest.raises(ConfigError):
        load_config()


def test_invalid_identity_mode(monkeypatch):
    monkeypatch.setenv("SIDECAR_API_KEY", "k")
    monkeypatch.setenv("IDENTITY_MODE", "bogus")
    with pytest.raises(ConfigError):
        load_config()


def test_on_unresolved_only_deny(monkeypatch):
    monkeypatch.setenv("SIDECAR_API_KEY", "k")
    monkeypatch.setenv("ON_UNRESOLVED_IDENTITY", "service_account")
    with pytest.raises(ConfigError):
        load_config()


def test_passthrough_requires_connected_app(monkeypatch):
    monkeypatch.setenv("SIDECAR_API_KEY", "k")
    monkeypatch.setenv("IDENTITY_MODE", "passthrough")
    monkeypatch.setenv("TRUST_EASY_AUTH", "true")
    with pytest.raises(ConfigError):  # no TABLEAU_SERVER / connected app
        load_config()


def test_passthrough_requires_easy_auth(monkeypatch):
    monkeypatch.setenv("SIDECAR_API_KEY", "k")
    monkeypatch.setenv("IDENTITY_MODE", "passthrough")
    monkeypatch.setenv("TABLEAU_SERVER", "https://x.online.tableau.com")
    monkeypatch.setenv("TABLEAU_CONNECTED_APP_CLIENT_ID", "c")
    monkeypatch.setenv("TABLEAU_CONNECTED_APP_SECRET_ID", "s")
    monkeypatch.setenv("TABLEAU_CONNECTED_APP_SECRET_VALUE", "v")
    # TRUST_EASY_AUTH defaults false -> passthrough can't get a UPN -> error
    with pytest.raises(ConfigError):
        load_config()


def test_passthrough_transform_requires_domains(monkeypatch):
    for k, v in {
        "SIDECAR_API_KEY": "k", "IDENTITY_MODE": "passthrough", "TRUST_EASY_AUTH": "true",
        "TABLEAU_SERVER": "https://x", "TABLEAU_CONNECTED_APP_CLIENT_ID": "c",
        "TABLEAU_CONNECTED_APP_SECRET_ID": "s", "TABLEAU_CONNECTED_APP_SECRET_VALUE": "v",
        "UPN_MAPPING_MODE": "transform",
    }.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError):
        load_config()


def test_passthrough_full_ok(monkeypatch):
    for k, v in {
        "SIDECAR_API_KEY": "k", "IDENTITY_MODE": "passthrough", "TRUST_EASY_AUTH": "true",
        "TABLEAU_SERVER": "https://x.online.tableau.com/", "TABLEAU_CONNECTED_APP_CLIENT_ID": "c",
        "TABLEAU_CONNECTED_APP_SECRET_ID": "s", "TABLEAU_CONNECTED_APP_SECRET_VALUE": "v",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = load_config()
    assert cfg.is_passthrough
    assert cfg.tableau_server == "https://x.online.tableau.com"  # trailing slash trimmed

"""Unit tests for identity extraction, UPN mapping, Connected App JWT, and the token cache."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from config import DEFAULT_JWT_SCOPES
from identity import (
    CallerIdentity,
    IdentityError,
    TokenCache,
    build_connected_app_jwt,
    cache_key,
    extract_caller_identity,
    map_upn_to_tableau_username,
)
from conftest import make_config


def _decode_segment(seg: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))


def test_jwt_structure_and_signature():
    token = build_connected_app_jwt("cid", "sid", "topsecret", "alice@x.com", list(DEFAULT_JWT_SCOPES))
    h, p, s = token.split(".")
    header = _decode_segment(h)
    payload = _decode_segment(p)
    assert header == {"alg": "HS256", "kid": "sid", "iss": "cid"}
    assert payload["iss"] == "cid"
    assert payload["aud"] == "tableau"
    assert payload["sub"] == "alice@x.com"
    assert payload["scp"] == list(DEFAULT_JWT_SCOPES)
    assert payload["exp"] - int(time.time()) <= 600
    expected = hmac.new(b"topsecret", f"{h}.{p}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64encode(expected).rstrip(b"=").decode() == s


def test_jwt_ttl_capped_at_10_min():
    token = build_connected_app_jwt("cid", "sid", "sv", "u", ["tableau:content:read"], ttl_seconds=99999)
    payload = _decode_segment(token.split(".")[1])
    assert payload["exp"] - int(time.time()) <= 600


def test_jwt_requires_all_fields():
    with pytest.raises(IdentityError):
        build_connected_app_jwt("", "sid", "sv", "u", ["s"])


def _principal_blob(claims: dict) -> str:
    payload = {"claims": [{"typ": k, "val": v} for k, v in claims.items()]}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_extract_identity_from_principal_name_header():
    headers = {"x-ms-client-principal-name": "bob@contoso.com", "x-ms-client-principal-id": "oid-9"}
    ident = extract_caller_identity(headers)
    assert ident.upn == "bob@contoso.com"
    assert ident.object_id == "oid-9"


def test_extract_identity_from_blob_claims():
    blob = _principal_blob({
        "preferred_username": "carol@contoso.com",
        "http://schemas.microsoft.com/identity/claims/tenantid": "tid-7",
        "http://schemas.microsoft.com/identity/claims/objectidentifier": "oid-7",
    })
    ident = extract_caller_identity({"x-ms-client-principal": blob})
    assert ident.upn == "carol@contoso.com"
    assert ident.tenant_id == "tid-7"
    assert ident.object_id == "oid-7"


def test_extract_identity_none_when_absent():
    assert extract_caller_identity({}) is None


def test_map_direct():
    cfg = make_config(identity_mode="passthrough", upn_mapping_mode="direct", trust_easy_auth=True)
    assert map_upn_to_tableau_username("alice@contoso.com", cfg) == "alice@contoso.com"


def test_map_transform_matching_domain():
    cfg = make_config(
        identity_mode="passthrough", upn_mapping_mode="transform",
        upn_domain_from="contoso.com", upn_domain_to="tableau.example.com", trust_easy_auth=True,
    )
    assert map_upn_to_tableau_username("alice@contoso.com", cfg) == "alice@tableau.example.com"


def test_map_transform_wrong_domain_fails_closed():
    cfg = make_config(
        identity_mode="passthrough", upn_mapping_mode="transform",
        upn_domain_from="contoso.com", upn_domain_to="t.com", trust_easy_auth=True,
    )
    with pytest.raises(IdentityError):
        map_upn_to_tableau_username("eve@evil.com", cfg)


def test_map_explicit_hit_and_miss():
    cfg = make_config(
        identity_mode="passthrough", upn_mapping_mode="explicit",
        upn_explicit_map={"alice@contoso.com": "alice.t"}, trust_easy_auth=True,
    )
    assert map_upn_to_tableau_username("Alice@Contoso.com", cfg) == "alice.t"  # case-insensitive
    with pytest.raises(IdentityError):
        map_upn_to_tableau_username("bob@contoso.com", cfg)


def test_cache_key_isolates_tenant_and_oid():
    cfg = make_config(identity_mode="passthrough", trust_easy_auth=True)
    a = cache_key(cfg, CallerIdentity("u@x.com", "oid-A", "tenant-A"), "u@x.com")
    b = cache_key(cfg, CallerIdentity("u@x.com", "oid-B", "tenant-B"), "u@x.com")
    assert a != b  # same UPN, different tenant/oid must NOT share a cache entry


def test_token_cache_set_get_evict():
    cache = TokenCache(ttl_seconds=1800)
    cache.set(("k",), "tok")
    assert cache.get(("k",)) == "tok"
    cache.evict(("k",))
    assert cache.get(("k",)) is None


def test_token_cache_expiry(monkeypatch):
    cache = TokenCache(ttl_seconds=10)
    now = [1000.0]
    monkeypatch.setattr("identity.time.time", lambda: now[0])
    cache.set(("k",), "tok")
    assert cache.get(("k",)) == "tok"
    now[0] += 11
    assert cache.get(("k",)) is None

"""Accounts and sessions for the multi-tenant Asclepius service.

Identity comes from **Sign in with Apple** (the iOS app sends the identity
token it got from AuthenticationServices; we verify the RS256 signature
against Apple's published JWKS and the audience against our bundle id).
Sessions are our own: a short-lived HS256 access JWT plus a long-lived,
rotating refresh token stored hashed. A separate, deliberately email-only
"dev login" exists for tests and simulator development and must never be
enabled in production.

Account data lives in a small global ``auth.db`` (users, refresh tokens,
device push tokens). Health data does NOT live here — each user has their own
database, see ``tenancy.py``.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

from . import config, tenancy

log = logging.getLogger("asclepius.auth")

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
# How long a fetched Apple key set is trusted before re-fetching.
_JWKS_TTL_SEC = 24 * 60 * 60


class AuthError(Exception):
    """Any failure to authenticate. Maps to a 401 at the API layer."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    apple_sub    TEXT UNIQUE,          -- Apple's stable subject for this user
    email        TEXT,
    name         TEXT,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT
);

-- Refresh tokens are stored as SHA-256 hashes: a leaked auth.db must not be
-- exchangeable for sessions. Rotation: each successful refresh revokes the
-- presented token and issues a new one.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);

-- One row per iOS device that registered for APNs push.
CREATE TABLE IF NOT EXISTS device_tokens (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    platform    TEXT NOT NULL DEFAULT 'ios',
    environment TEXT NOT NULL DEFAULT 'production',  -- 'sandbox' | 'production'
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_device_user ON device_tokens(user_id);
"""


def _auth_db_path() -> Path:
    return Path(config.DATA_DIR) / "auth.db"


def connect_auth() -> sqlite3.Connection:
    path = _auth_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Signing secret
# ---------------------------------------------------------------------------
_secret_lock = threading.Lock()
_secret_cache: bytes | None = None


def _signing_secret() -> bytes:
    """The HS256 secret for our access tokens.

    Prefer ``ASCLEPIUS_SECRET`` from the environment; otherwise generate one
    once and persist it under the data dir so sessions survive restarts.
    """
    global _secret_cache
    import os

    env = os.environ.get("ASCLEPIUS_SECRET", "")
    if env:
        return env.encode("utf-8")
    with _secret_lock:
        if _secret_cache is not None:
            return _secret_cache
        path = Path(config.DATA_DIR) / "secret.key"
        if path.exists():
            _secret_cache = path.read_bytes().strip()
        else:
            _secret_cache = secrets.token_urlsafe(48).encode("ascii")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_secret_cache)
            try:
                path.chmod(0o600)
            except OSError:
                pass
        return _secret_cache


# ---------------------------------------------------------------------------
# Minimal JWT (HS256) for our own access tokens
# ---------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _jwt_encode(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = hmac.new(_signing_secret(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def _jwt_decode(token: str) -> dict:
    try:
        header_b64, body_b64, sig_b64 = token.split(".")
    except ValueError:
        raise AuthError("Malformed token.")
    signing_input = f"{header_b64}.{body_b64}".encode("ascii")
    expected = hmac.new(_signing_secret(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
        raise AuthError("Bad token signature.")
    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(body_b64))
    except (ValueError, json.JSONDecodeError):
        raise AuthError("Malformed token.")
    if header.get("alg") != "HS256":
        raise AuthError("Unexpected token algorithm.")
    if payload.get("exp", 0) < time.time():
        raise AuthError("Token expired.")
    return payload


# ---------------------------------------------------------------------------
# Sign in with Apple: identity-token verification
# ---------------------------------------------------------------------------
_jwks_lock = threading.Lock()
_jwks_cache: tuple[float, list[dict]] | None = None


def _apple_jwks() -> list[dict]:
    global _jwks_cache
    with _jwks_lock:
        if _jwks_cache and time.time() - _jwks_cache[0] < _JWKS_TTL_SEC:
            return _jwks_cache[1]
    req = urllib.request.Request(APPLE_JWKS_URL,
                                 headers={"User-Agent": "asclepius"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        keys = json.loads(resp.read()).get("keys", [])
    with _jwks_lock:
        _jwks_cache = (time.time(), keys)
    return keys


def _rsa_public_key(jwk: dict):
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    return RSAPublicNumbers(e, n).public_key()


def verify_apple_identity_token(identity_token: str) -> dict:
    """Verify an Apple identity token and return its claims.

    Checks the RS256 signature against Apple's JWKS (matched by ``kid``,
    with one forced re-fetch on miss so key rotation doesn't strand users),
    then issuer, audience (our bundle id) and expiry.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        header_b64, body_b64, sig_b64 = identity_token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(body_b64))
        signature = _b64url_decode(sig_b64)
    except (ValueError, json.JSONDecodeError):
        raise AuthError("Malformed Apple identity token.")

    kid = header.get("kid")
    jwk = next((k for k in _apple_jwks() if k.get("kid") == kid), None)
    if jwk is None:
        # Apple rotated keys since our cache — force a refresh and retry once.
        global _jwks_cache
        with _jwks_lock:
            _jwks_cache = None
        jwk = next((k for k in _apple_jwks() if k.get("kid") == kid), None)
    if jwk is None:
        raise AuthError("Unknown Apple signing key.")

    try:
        _rsa_public_key(jwk).verify(
            signature,
            f"{header_b64}.{body_b64}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        raise AuthError("Apple identity token signature is invalid.")

    if claims.get("iss") != APPLE_ISSUER:
        raise AuthError("Apple identity token has the wrong issuer.")
    aud = claims.get("aud")
    if aud != config.apple_bundle_id():
        raise AuthError("Apple identity token was issued for a different app.")
    if claims.get("exp", 0) < time.time():
        raise AuthError("Apple identity token has expired.")
    if not claims.get("sub"):
        raise AuthError("Apple identity token is missing a subject.")
    return claims


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _user_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "apple_sub": r["apple_sub"], "email": r["email"],
            "name": r["name"], "created_at": r["created_at"]}


def upsert_apple_user(apple_sub: str, email: str | None = None,
                      name: str | None = None) -> dict:
    """Find or create the user for an Apple subject.

    Apple only sends email/name on the *first* authorization, so stored
    values are kept unless the new call actually provides them.
    """
    now = _iso(_now())
    with connect_auth() as conn:
        row = conn.execute("SELECT * FROM users WHERE apple_sub = ?",
                           (apple_sub,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET email = COALESCE(?, email), "
                "name = COALESCE(?, name), last_seen_at = ? WHERE id = ?",
                (email or None, name or None, now, row["id"]))
            row = conn.execute("SELECT * FROM users WHERE id = ?",
                               (row["id"],)).fetchone()
            return _user_row(row)
        cur = conn.execute(
            "INSERT INTO users (apple_sub, email, name, created_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)", (apple_sub, email, name, now, now))
        row = conn.execute("SELECT * FROM users WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
        return _user_row(row)


def upsert_dev_user(email: str, name: str | None = None) -> dict:
    """Development-only login by email (guarded by ASCLEPIUS_DEV_LOGIN)."""
    # Dev users are namespaced into apple_sub so the unique key still applies.
    return upsert_apple_user(f"dev:{email.strip().lower()}",
                             email=email.strip().lower(), name=name)


def get_user(user_id: int) -> dict | None:
    with connect_auth() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?",
                           (int(user_id),)).fetchone()
    return _user_row(row) if row else None


def list_user_ids() -> list[int]:
    with connect_auth() as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM users")]


def delete_user(user_id: int) -> bool:
    """Full account deletion: auth rows plus the user's entire data directory."""
    with connect_auth() as conn:
        conn.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (int(user_id),))
        conn.execute("DELETE FROM device_tokens WHERE user_id = ?", (int(user_id),))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (int(user_id),))
    tenancy.delete_user_data(int(user_id))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(user: dict) -> dict:
    """Issue a fresh access + refresh token pair for a user."""
    now = _now()
    access = _jwt_encode({
        "sub": str(user["id"]),
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + config.ACCESS_TOKEN_TTL_SEC,
    })
    refresh = secrets.token_urlsafe(48)
    with connect_auth() as conn:
        conn.execute(
            "INSERT INTO refresh_tokens (token_hash, user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (_hash_token(refresh), int(user["id"]), _iso(now),
             _iso(now + _dt.timedelta(seconds=config.REFRESH_TOKEN_TTL_SEC))))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": config.ACCESS_TOKEN_TTL_SEC,
        "user": {"id": user["id"], "email": user["email"], "name": user["name"]},
    }


def refresh_session(refresh_token: str) -> dict:
    """Exchange a live refresh token for a new session (the old one is revoked)."""
    token_hash = _hash_token(refresh_token or "")
    now = _iso(_now())
    with connect_auth() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?",
            (token_hash,)).fetchone()
        if (row is None or row["revoked"]
                or row["expires_at"] < now):
            raise AuthError("Refresh token is invalid or expired.")
        conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
                     (token_hash,))
        user_id = row["user_id"]
    user = get_user(user_id)
    if user is None:
        raise AuthError("Account no longer exists.")
    return create_session(user)


def revoke_refresh_token(refresh_token: str) -> bool:
    with connect_auth() as conn:
        cur = conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
            (_hash_token(refresh_token or ""),))
    return cur.rowcount > 0


def verify_access_token(token: str) -> dict:
    """Validate a bearer token and return the user it belongs to."""
    payload = _jwt_decode(token)
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise AuthError("Malformed token subject.")
    user = get_user(user_id)
    if user is None:
        raise AuthError("Account no longer exists.")
    return user


# ---------------------------------------------------------------------------
# Device push tokens (APNs)
# ---------------------------------------------------------------------------
def register_device(user_id: int, token: str, platform: str = "ios",
                    environment: str = "production") -> None:
    if environment not in ("sandbox", "production"):
        environment = "production"
    with connect_auth() as conn:
        conn.execute(
            "INSERT INTO device_tokens (token, user_id, platform, environment, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(token) DO UPDATE SET user_id=excluded.user_id, "
            "platform=excluded.platform, environment=excluded.environment",
            (token, int(user_id), platform, environment, _iso(_now())))


def delete_device(token: str, user_id: int | None = None) -> bool:
    with connect_auth() as conn:
        if user_id is None:
            cur = conn.execute("DELETE FROM device_tokens WHERE token = ?", (token,))
        else:
            cur = conn.execute(
                "DELETE FROM device_tokens WHERE token = ? AND user_id = ?",
                (token, int(user_id)))
    return cur.rowcount > 0


def list_devices(user_id: int) -> list[dict]:
    with connect_auth() as conn:
        rows = conn.execute(
            "SELECT token, platform, environment, created_at FROM device_tokens "
            "WHERE user_id = ?", (int(user_id),)).fetchall()
    return [dict(r) for r in rows]

"""Native iOS push via APNs (token-based auth).

The transport counterpart of ``push.py`` for the iOS app: builds the provider
JWT (ES256, signed with the .p8 key from the Apple Developer portal), then
POSTs alerts to APNs over HTTP/2 for every registered device token.

Entirely optional — without APNS_KEY/APNS_KEY_ID/APNS_TEAM_ID configured,
``enabled()`` is False and sends are no-ops, so local mode and web-push-only
deployments are unaffected.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from . import auth, config

log = logging.getLogger("asclepius.apns")

_HOSTS = {
    "production": "https://api.push.apple.com",
    "sandbox": "https://api.sandbox.push.apple.com",
}

# APNs provider tokens are valid 20-60 minutes; refresh ours after 45.
_PROVIDER_TOKEN_TTL_SEC = 45 * 60

_token_lock = threading.Lock()
_token_cache: tuple[float, str] | None = None

_client_lock = threading.Lock()
_client = None


def enabled() -> bool:
    cfg = config.apns_config()
    return bool(cfg["key"] and cfg["key_id"] and cfg["team_id"])


def _private_key_pem() -> bytes:
    """The .p8 signing key: APNS_KEY holds either the PEM itself or a path."""
    raw = config.apns_config()["key"]
    if "BEGIN" in raw:
        return raw.replace("\\n", "\n").encode("ascii")
    return Path(raw).read_bytes()


def _provider_token() -> str:
    """The ES256-signed JWT APNs requires in the authorization header."""
    global _token_cache
    with _token_lock:
        if _token_cache and time.time() - _token_cache[0] < _PROVIDER_TOKEN_TTL_SEC:
            return _token_cache[1]

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    from .auth import _b64url  # same base64url everywhere

    cfg = config.apns_config()
    key = serialization.load_pem_private_key(_private_key_pem(), password=None)
    header = _b64url(json.dumps({"alg": "ES256", "kid": cfg["key_id"]}).encode())
    claims = _b64url(json.dumps({"iss": cfg["team_id"],
                                 "iat": int(time.time())}).encode())
    signing_input = f"{header}.{claims}".encode("ascii")
    der_sig = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # APNs wants the raw r||s signature, not DER.
    r, s = utils.decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = f"{header}.{claims}.{_b64url(raw_sig)}"
    with _token_lock:
        _token_cache = (time.time(), token)
    return token


def _http_client():
    """A shared HTTP/2 client (APNs requires HTTP/2)."""
    global _client
    with _client_lock:
        if _client is None:
            import httpx

            _client = httpx.Client(http2=True, timeout=10.0)
        return _client


def build_payload(title: str, body: str, *, ntype: str = "",
                  url: str = "/", tag: str = "asclepius",
                  data: dict | None = None) -> dict:
    return {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "thread-id": tag,
        },
        # Mirrors the web-push payload so the app can route taps the same way.
        "ntype": ntype,
        "url": url,
        "data": data or {},
    }


def _send_one(device: dict, payload: dict) -> bool:
    """Deliver to one device. Prunes tokens APNs reports as gone."""
    host = _HOSTS.get(device.get("environment", "production"), _HOSTS["production"])
    token = device["token"]
    try:
        resp = _http_client().post(
            f"{host}/3/device/{token}",
            json=payload,
            headers={
                "authorization": f"bearer {_provider_token()}",
                "apns-topic": config.apns_config()["topic"],
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
        )
    except Exception as exc:  # noqa: BLE001 - a dead device must not kill a job
        log.warning("APNs delivery error: %s", exc)
        return False
    if resp.status_code == 200:
        return True
    reason = ""
    try:
        reason = resp.json().get("reason", "")
    except Exception:  # noqa: BLE001
        pass
    if resp.status_code == 410 or reason in ("BadDeviceToken", "Unregistered",
                                             "DeviceTokenNotForTopic"):
        auth.delete_device(token)
        log.info("Pruned dead APNs token (%s)", reason or resp.status_code)
    else:
        log.warning("APNs delivery failed (%s): %s", resp.status_code, reason)
    return False


def send_to_user(user_id: int, title: str, body: str, **opts) -> dict:
    """Send one alert to every iOS device a user has registered."""
    if not enabled():
        return {"sent": 0, "failed": 0, "devices": 0, "disabled": True}
    devices = auth.list_devices(user_id)
    if not devices:
        return {"sent": 0, "failed": 0, "devices": 0}
    payload = build_payload(title, body, **opts)
    sent = sum(1 for d in devices if _send_one(d, payload))
    return {"sent": sent, "failed": len(devices) - sent, "devices": len(devices)}

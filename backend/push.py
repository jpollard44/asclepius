"""Web push delivery for Asclepius.

Sends VAPID-signed push messages to the browser subscriptions stored by
``store.py``. The actual scheduling of *when* to send lives in ``scheduler.py``;
this module is the transport: build a payload, sign it, fan it out to every
subscription, and prune any the push service reports as gone.

Push is optional. If no VAPID private key is configured (see
``scripts/gen_vapid.py``) everything here degrades gracefully — ``enabled()`` is
False and sends become no-ops — so the app runs fine without it.
"""
from __future__ import annotations

import base64
import json
import logging

from pywebpush import WebPushException, webpush

from . import apns, store, tenancy
from .config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUBJECT

log = logging.getLogger("asclepius.push")

# TTL the push service holds an undelivered message before dropping it (seconds).
# A day is plenty for a health nudge — there's no value delivering "log lunch"
# two days late.
_TTL = 24 * 60 * 60


def enabled() -> bool:
    """True when a VAPID keypair is configured and push can actually be sent."""
    return bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY)


def any_channel_enabled() -> bool:
    """True when at least one delivery channel (web push or APNs) works."""
    return enabled() or apns.enabled()


def public_key() -> str:
    """The base64url VAPID public key the frontend needs to subscribe."""
    return VAPID_PUBLIC_KEY


def _vapid_private_pem() -> str:
    """Rebuild a PKCS8 PEM from the raw base64url private scalar in .env.

    pywebpush accepts the VAPID key as a PEM string (it branches on the newline);
    we store only the compact raw scalar in .env, so reconstruct the key object
    and serialize it to PEM here. Cached after the first call.
    """
    if _vapid_private_pem._cache is not None:  # type: ignore[attr-defined]
        return _vapid_private_pem._cache  # type: ignore[attr-defined]
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    raw = VAPID_PRIVATE_KEY + "=" * (-len(VAPID_PRIVATE_KEY) % 4)  # restore padding
    priv_int = int.from_bytes(base64.urlsafe_b64decode(raw), "big")
    key = ec.derive_private_key(priv_int, ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    _vapid_private_pem._cache = pem  # type: ignore[attr-defined]
    return pem


_vapid_private_pem._cache = None  # type: ignore[attr-defined]


def build_payload(title: str, body: str, *, tag: str = "asclepius",
                  url: str = "/", icon: str = "/icons/icon-192.png",
                  badge: str = "/icons/badge.png", ntype: str = "",
                  data: dict | None = None) -> str:
    """JSON string the service worker reads in its `push` handler."""
    payload = {
        "title": title,
        "body": body,
        "tag": tag,
        "icon": icon,
        "badge": badge,
        "url": url,
        "ntype": ntype,
        "data": data or {},
    }
    return json.dumps(payload)


def _send_one(subscription: dict, payload: str) -> bool:
    """Deliver one push. Returns True on success; prunes dead subscriptions.

    A 404/410 from the push service means the subscription is permanently gone
    (browser uninstalled, user cleared site data) — we delete it so it isn't
    retried forever. Other errors are logged and reported as a failure.
    """
    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=_vapid_private_pem(),
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=_TTL,
        )
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            endpoint = subscription.get("endpoint", "")
            store.delete_push_subscription(endpoint)
            log.info("Pruned expired push subscription (%s)", status)
        else:
            log.warning("Push delivery failed (%s): %s", status, exc)
        return False
    except Exception as exc:  # noqa: BLE001 - never let a bad sub crash a job
        log.warning("Push delivery error: %s", exc)
        return False


def send_to_all(title: str, body: str, **opts) -> dict:
    """Send one notification to every device the current user has.

    Fans out over both channels: web-push subscriptions (stored in the
    tenant's own DB) and, when a user is bound to the context, their APNs
    device tokens. Returns combined counts. Does nothing (and reports it)
    when no channel is configured or there is nothing to send to.
    """
    if not any_channel_enabled():
        return {"sent": 0, "failed": 0, "subscriptions": 0, "disabled": True}

    sent = failed = targets = 0
    if enabled():
        subs = store.list_push_subscriptions()
        if subs:
            payload = build_payload(title, body, **opts)
            ok = sum(1 for s in subs if _send_one(s, payload))
            sent += ok
            failed += len(subs) - ok
            targets += len(subs)

    user_id = tenancy.current_user_id()
    if user_id is not None and apns.enabled():
        apns_opts = {k: v for k, v in opts.items()
                     if k in ("ntype", "url", "tag", "data")}
        result = apns.send_to_user(user_id, title, body, **apns_opts)
        sent += result.get("sent", 0)
        failed += result.get("failed", 0)
        targets += result.get("devices", 0)

    return {"sent": sent, "failed": failed, "subscriptions": targets}


def send_test(db_path=None) -> dict:
    """Fire a one-off confirmation push (backs the "Send test" settings button)."""
    return send_to_all(
        "🔔 Notifications on",
        "Asclepius will nudge you here. You can fine-tune these in Settings.",
        tag="asclepius-test", ntype="test")

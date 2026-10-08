"""Decide whether an Echoport target's FastDeploy service token must be re-issued.

Fed to ``manage.py shell`` on stdin by ``tasks/register_echoport.yml``. It
prints one JSON line with metadata only; the token itself is never printed.
Importing the file (as the unit tests do) only defines the functions.

A token is reused only when it is a recorded (``jti``) service token for the
expected service that is valid for more than the renewal window. Anything
else (missing, undecodable, wrong scope, legacy token without ``jti``,
expiring) is reported with a reason, and the caller issues a new token.
"""

import base64
import json
import os
import re
import time

JWT_SHAPE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def token_claims(token):
    """Return the unverified JWT payload as a dict, or None if undecodable.

    Only a complete compact JWT (three non-empty base64url segments) counts;
    a truncated token or one without a signature is undecodable, so it is
    replaced rather than kept.
    """
    if not isinstance(token, str) or not JWT_SHAPE.fullmatch(token):
        return None
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")).decode("utf-8"))
    except (AttributeError, IndexError, UnicodeError, ValueError):
        return None
    return claims if isinstance(claims, dict) else None


def rotation_reason(token, service, renewal_days, now):
    """Return why the token must be re-issued, or None if it can be reused."""
    if not token:
        return "missing"
    claims = token_claims(token)
    if claims is None:
        return "undecodable"
    if claims.get("type") != "service" or claims.get("service") != service:
        return "wrong_scope"
    if not claims.get("jti"):
        return "legacy_without_jti"
    try:
        expires_at = int(claims["exp"])
    except (KeyError, TypeError, ValueError):
        return "no_expiry"
    if expires_at <= now + renewal_days * 86400:
        return "expiring"
    return None


def token_status(token, service, renewal_days, now):
    """Metadata about the token that is safe to print (never the token)."""
    claims = token_claims(token) if token else None
    reason = rotation_reason(token, service, renewal_days, now)
    expires_at = None
    if claims is not None:
        try:
            expires_at = int(claims["exp"])
        except (KeyError, TypeError, ValueError):
            expires_at = None
    jti = claims.get("jti") if claims is not None else None
    return {
        "has_token": bool(token),
        "has_jti": bool(jti),
        "previous_jti": jti if isinstance(jti, str) else None,
        "expires_at": expires_at,
        "requires_rotation": reason is not None,
        "reason": reason or "valid",
    }


def main():
    from backups.models import BackupTarget

    target_names = json.loads(os.environ["SERVICE_TOKEN_STATUS_TARGETS"])
    service = os.environ["SERVICE_TOKEN_STATUS_SERVICE"]
    renewal_days = int(os.environ["SERVICE_TOKEN_STATUS_RENEWAL_DAYS"])
    target = None
    for name in target_names:
        target = BackupTarget.objects.filter(name=name).first()
        if target is not None:
            break
    token = target.service_token if target is not None else ""
    status = token_status(token, service, renewal_days, int(time.time()))
    status["target"] = target.name if target is not None else None
    print(json.dumps(status, sort_keys=True))


if os.environ.get("SERVICE_TOKEN_STATUS_TARGETS"):
    main()

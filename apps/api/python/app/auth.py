"""Minimal JWT verification for the one python-api route that needs it:
POST /architect/run. python-api otherwise has no auth of its own (see
CLAUDE.md's "Architecture / trust boundaries") -- it's meant to be
reachable only through the gateway (which already enforces JWT on
sensitive routes) or web's nginx /py-api/ proxy. That nginx proxy exposes
python-api's *entire* route surface with no auth check of its own,
though, so a route that can trigger a real git push + PR against the
live repo cannot rely on "the gateway already checked this" -- it has to
verify the token itself. This mirrors apps/gateway/src/middleware/auth.rs's
Claims shape (`sub`, `exp`) and uses the same JWT_SECRET, HS256 default.
"""

from __future__ import annotations

import jwt
from fastapi import HTTPException, Request

from app.config import get_settings

# A "connect the dots" audit found that copying apps/gateway/.env.example's
# literal JWT_SECRET=change-me-in-production straight into a real .env
# satisfies docker-compose's `${JWT_SECRET:?...}` non-empty guard, and used
# to pass the `not settings.jwt_secret` check below too -- but it's just as
# forgeable as leaving JWT_SECRET unset, since it's a known public string in
# this repo's own example file. Anyone who's read this open-source repo can
# mint a valid token for POST /architect/run (a route that can trigger a
# real git commit + PR) using this exact secret. Treated identically to the
# missing-secret case, not just warned about, since this route already
# fails closed rather than open.
_KNOWN_PLACEHOLDER_SECRETS = {"change-me-in-production"}


def require_user_id(request: Request) -> str:
    settings = get_settings()
    if not settings.jwt_secret or settings.jwt_secret in _KNOWN_PLACEHOLDER_SECRETS:
        # No secret configured at all (or still the well-known example
        # placeholder) -- fail closed, not open. A route gated on this
        # dependency must never silently become anonymous or forgeable.
        raise HTTPException(status_code=503, detail="JWT_SECRET not configured; this route is disabled")

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = auth[len("Bearer ") :]
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token missing sub claim")
    return sub

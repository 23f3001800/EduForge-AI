"""An optional shared key on the endpoints that spend money.

This is not an authentication system and does not pretend to be one: there are
no accounts, no sessions and no per-user anything, so it cannot say *who* made a
request. It answers one narrower question — may this caller start work that
costs money — and that is the question a public demo actually has.

It exists because the deployed instance runs on a paid Azure OpenAI key with no
login in front of it. A full pipeline run is dozens of model calls, so an open
job endpoint is an open invoice, and a link that gets shared once is a link that
can be replayed.

Off unless ``ACCESS_KEY`` is set. That default matters: the local development
path (``make dev``) and every evaluator who clones the repo and runs it with
their own key must keep working with no configuration, because a demo nobody can
start is worse than one that costs its owner nothing to run. Deployments that
spend the *maintainer's* money set the variable; deployments that spend the
runner's own do not need to.

Reading and browsing stay open by design. The samples, packages, evaluations and
artifacts cost nothing to serve, and gating them would defeat the purpose of
publishing a demonstration at all.
"""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException

from api.deps import get_app_settings
from core.config import Settings

__all__ = ["require_access"]


async def require_access(
    x_access_key: str | None = Header(default=None, alias="X-Access-Key"),
    settings: Settings = Depends(get_app_settings),
) -> None:
    """Allow the request when no key is configured, or when the key matches.

    Compared with ``hmac.compare_digest`` rather than ``==``. The timing
    difference on a short string is small and the attack is awkward over a
    network, but a constant-time comparison is one call and there is no reason
    to hand out the prefix-length oracle that ``==`` provides.
    """
    expected = (getattr(settings, "access_key", None) or "").strip()
    if not expected:
        return

    supplied = (x_access_key or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            401,
            detail={
                "code": "access_key_required",
                "message": (
                    "This instance requires an access key. Send it as the "
                    "X-Access-Key header, or run your own instance — see the README."
                ),
            },
        )

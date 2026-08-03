"""Test-wide configuration.

Tests run under the ``ci`` profile, which is the one profile that requires no
credential: the replay provider serves recorded cassettes, so the suite never
touches a network, never needs a key, and never spends a token.

That the suite *fails loudly* without this is the point — `core.config` refuses to
boot when a profile's required credential is missing, which is far better than
starting successfully and dying on the first upload.
"""

from __future__ import annotations

import os

import pytest

# Set before anything imports core.config, whose Settings are constructed eagerly.
os.environ.setdefault("LLM_PROFILE", "ci")

# The suite runs against an *open* instance unless a test says otherwise.
#
# Settings read the developer's own .env, so a maintainer who sets ACCESS_KEY to
# gate their deployment silently gated their test suite too: every upload in
# every test began returning 401 and 29 tests failed for a reason that had
# nothing to do with the code under test. A suite whose result depends on an
# untracked local file is not measuring the repository.
#
# Forced rather than defaulted — `setdefault` would still lose to a value
# already in the environment, which is exactly the case being defended against.
# Tests that exercise the gate set the value on Settings directly.
os.environ["ACCESS_KEY"] = ""


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Settings are cached per process; a test that changes env must not leak."""
    from core.config import get_settings

    get_settings.cache_clear()

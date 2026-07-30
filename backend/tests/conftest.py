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


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Settings are cached per process; a test that changes env must not leak."""
    from core.config import get_settings

    get_settings.cache_clear()

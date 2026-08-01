"""The stage roster — what the pipeline actually runs.

``build_stages`` is the single place that decides which stages are real, so it is
the single place worth asserting against. Without these tests a stage can be
written, imported, lint-clean and fully tested while never being reached by a
job — which was true of stages 4-8 until they were wired.
"""

from __future__ import annotations

from contracts.primitives import STAGE_NAMES
from core.config import REPO_ROOT
from core.llm.client import LLMClient
from core.llm.router import load_routing
from orchestration.pipeline import REMAINING_STUBS, build_stages
from stages.stubs import StubStage


def _roster() -> list:
    # The `ci` profile routes every stage to the replay provider, so this needs
    # no key and makes no network call.
    routing = load_routing(REPO_ROOT / "config" / "models.yaml", "ci")
    llm = LLMClient(routing=routing, adapters={})
    return build_stages(
        llm=llm,
        payload=b"%PDF-1.7\n",
        filename="a.pdf",
        mime="application/pdf",
        max_bytes=1024,
        max_pages=10,
        parse_timeout_s=5.0,
    )


def test_the_roster_covers_every_stage_exactly_once_in_order() -> None:
    """Progress weights, resume, and the graph all key on this order."""
    assert [stage.name for stage in _roster()] == list(STAGE_NAMES)


def test_every_stage_is_real() -> None:
    real = [stage for stage in _roster() if not isinstance(stage, StubStage)]
    assert [stage.name for stage in real] == list(STAGE_NAMES)


def test_only_the_declared_stubs_remain() -> None:
    """If this fails, either a stub was replaced or one crept back in undeclared."""
    stubs = [stage.name for stage in _roster() if isinstance(stage, StubStage)]
    assert stubs == list(REMAINING_STUBS)


def test_every_stage_implements_the_stage_protocol() -> None:
    for stage in _roster():
        assert hasattr(stage, "name")
        assert callable(getattr(stage, "run", None))

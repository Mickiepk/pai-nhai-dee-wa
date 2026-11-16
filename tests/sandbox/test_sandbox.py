"""Data-driven sandbox: every scenario in tests/sandbox/scenarios/*.yaml, plus determinism checks.

Known bugs are xfail(strict=True): when a fix lands the test XPASSes, fails the run, and the
`bug:` key must be removed from the scenario (regression policy, docs/TEST_POLICY.md).
"""

from __future__ import annotations

import pytest

from tests.sandbox.harness import determinism, load_scenarios, run_case, run_unseeded_twice

CASES = load_scenarios()


def _params(bug_key: str):
    out = []
    for c in CASES:
        marks = []
        if c.get(bug_key):
            marks.append(pytest.mark.xfail(strict=True, reason=c[bug_key]))
        out.append(pytest.param(c, id=c["id"], marks=marks))
    return out


@pytest.mark.parametrize("case", _params("bug"))
def test_scenario(case):
    result = run_case(case)
    assert result.passed, f"{case['id']} {case['title']}\n" + "\n".join(result.failures)


@pytest.mark.parametrize("case", _params("determinism_bug"))
def test_determinism(case):
    problems = determinism(case, runs=5)
    assert not problems, f"{case['id']} not deterministic: {problems}"


def test_session_id_is_deterministic_without_sandbox_seed():
    """BUG-20 regression: the engine takes an injectable `id_factory` (default stays random in prod), so
    two fresh runs of the same events give identical postback data (sid=...) with no monkeypatching."""
    case = next(c for c in CASES if c["id"] == "SBX-01")
    a, b = run_unseeded_twice(case)
    assert a.transcript == b.transcript and a.final_state == b.final_state

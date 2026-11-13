"""Regression check of router_classifier on the labeled corpus in tests/router_corpus.

tune, holdout and blind meet the acceptance criteria (deep recall >= 90%, chore recall >= 85%, false-nudge
<= 3%). blind2 is the honest number for prompts from a new author and misses the recall targets, so it
only guards against getting worse: false-nudge stays <= 3% and recall stays at least what 0.3.0 reached.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "router_corpus"))
import router_classifier  # noqa: E402  (conftest puts the plugin's hooks on the path)
import router_eval  # noqa: E402

ROWS = router_eval.load()
BLIND2_FLOOR = {"deep": 0.56, "chore": 0.64}  # 0.3.0, scored once on a frozen classifier


def result(split):
    return router_eval.evaluate(router_classifier.classify, [r for r in ROWS if r["split"] == split])


@pytest.mark.parametrize("split", ["tune", "holdout", "blind"])
def test_split_meets_the_criteria(split):
    assert router_eval.failed_criteria(result(split)) == []


def test_blind2_does_not_get_worse():
    res = result("blind2")
    assert res["n"] == 100
    assert res["false_nudge"] <= router_eval.MAX_FALSE_NUDGE
    for tier, floor in BLIND2_FLOOR.items():
        assert res["recall"][tier] >= floor, tier

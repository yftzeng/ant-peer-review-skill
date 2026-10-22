import pytest

from ant_peer_review.i18n import T
from ant_peer_review.rubric import (edit_rubric, final_impact, propose, s_curve_fit,
                                    validate_rubric)
from ant_peer_review.ui import ScriptedIO

SKIP = {"expertise": None, "role": None, "lens": None, "trust": None, "purpose": None}


def weights(r):
    return {d["key"]: d["weight"] for d in r["dimensions"]}


# @S-rubric-001
def test_default_weights():
    assert weights(propose(SKIP)) == {"macro": 30, "accuracy": 30, "micro": 20, "impact": 20}


# @S-rubric-002
def test_audience_shifts_weights():
    w = weights(propose(dict(SKIP, expertise="scholar")))
    assert w["accuracy"] > 30 and sum(w.values()) == 100 and min(w.values()) >= 5


# @S-rubric-003
def test_edit_weight_renormalizes():
    r = propose(SKIP)
    io = ScriptedIO(["2", "4", "40", "1"])
    r = edit_rubric(io, T("en"), r)
    w = weights(r)
    assert w["impact"] == 40 and sum(w.values()) == 100


# @S-rubric-004
def test_add_custom_dimension():
    io = ScriptedIO(["3", "brand voice", "10", "1"])
    r = edit_rubric(io, T("en"), propose(SKIP))
    w = weights(r)
    assert len(w) == 5 and w["custom-brand-voice"] == 10 and sum(w.values()) == 100


# @S-rubric-005
def test_s_curve_fit_table():
    assert s_curve_fit("startup", dict(SKIP, expertise="scholar", purpose="trend")) > 50
    assert s_curve_fit("startup", dict(SKIP, expertise="public", purpose="emotional")) < 50


# @S-rubric-006
def test_unverified_stage_not_scored():
    assert final_impact(80, 20, "cannot_verify") == 80
    assert final_impact(80, 20, "supported") == pytest.approx(65)


# @N-rubric-001
def test_validate_rejects_bad_sum():
    r = propose(SKIP)
    r["dimensions"][0]["weight"] += 1
    with pytest.raises(ValueError):
        validate_rubric(r)


# @S-rubric-007
def test_multi_values_average_shifts():
    from ant_peer_review.rubric import ADJUST, DEFAULT_WEIGHTS, _rebalance
    w = weights(propose(dict(SKIP, expertise=["scholar", "public"])))
    exp = dict(DEFAULT_WEIGHTS)
    for k in exp:
        exp[k] += (ADJUST[("expertise", "scholar")].get(k, 0)
                   + ADJUST[("expertise", "public")].get(k, 0)) / 2
    assert w == _rebalance(exp) and sum(w.values()) == 100


# @S-rubric-008
def test_s_curve_fit_share():
    fit = s_curve_fit("startup", dict(SKIP, expertise=["scholar", "public"], purpose=["trend"]))
    assert fit == pytest.approx(66.7, abs=0.05)

from ant_peer_review.backends.base import BackendError, Result
from ant_peer_review.factcheck import (build_ledger, check_claim, is_retryable, read_ledger,
                                       run_checks, snapshot, write_ledger)
from ant_peer_review.jsonio import write_json
from ant_peer_review.refresh import compute_consensus, factcheck_continue
from ant_peer_review.report import latest_version, write_report
from ant_peer_review.ui import ScriptedIO
from helpers import ScriptBackend, make_run, ok, review_data

TH = {"excellent": 85, "good": 70, "revise": 60}
CLAIM = {"id": "C01", "anchor": "D1.P02.S1", "text": "Revenue grew 40% in 2025",
         "type": "number", "status": "pending", "reason": "", "sources": [], "refs": []}


def search_result(status, urls, seen):
    return Result(model="", model_id="", data={
        "status": status, "reason": "r",
        "sources": [{"url": u, "supporting_excerpt": "e"} for u in urls]},
        tool_calls=[{"name": "WebSearch", "input": {"query": "q"}}],
        tool_results=["Links: " + " ".join(seen)])


# @S-factcheck-ledger-001
def test_ledger_merges_claims():
    reviews = {"opus": ok("opus", review_data(claims=[{}])),
               "sonnet": ok("sonnet", review_data(claims=[{}, {"id": "K2", "anchor": "D1.P03.S1",
                                                              "text": "“We lead”, said Ann",
                                                              "type": "quote"}]))}
    led = [c for c in build_ledger(reviews, [], ["opus", "sonnet"]) if c["id"] != "SC1"]
    assert len(led) == 2
    assert led[0]["extracted_by"] == ["opus", "sonnet"] and led[0]["refs"] == ["opus:K1", "sonnet:K1"]
    assert {c["status"] for c in led} == {"pending"}


# @S-factcheck-ledger-002
def test_source_not_in_search_results_dropped():
    b = ScriptBackend({("sonnet", "factcheck"): search_result(
        "supported", ["https://a.example/x", "https://b.example/y"], ["https://a.example/x"])})
    c = check_claim(b, "sonnet", CLAIM, "ctx", "en")
    assert c["status"] == "supported" and [s["url"] for s in c["sources"]] == ["https://a.example/x"]
    assert b.calls[0]["tools"] == ("WebSearch", "WebFetch")


# @S-factcheck-ledger-003
# @N-factcheck-ledger-001
def test_no_search_means_cannot_verify():
    b = ScriptBackend({("sonnet", "factcheck"): Result(model="", model_id="", data={
        "status": "supported", "reason": "", "sources": [{"url": "https://w.example",
                                                          "supporting_excerpt": "e"}]})})
    c = check_claim(b, "sonnet", CLAIM, "ctx", "en")
    assert (c["status"], c["reason"]) == ("cannot_verify", "no_search")
    b2 = ScriptBackend({("sonnet", "factcheck"): search_result("unsupported",
                                                               ["https://x.example"], [])})
    c2 = check_claim(b2, "sonnet", CLAIM, "ctx", "en")
    assert (c2["status"], c2["reason"]) == ("cannot_verify", "no_source")


# @S-factcheck-ledger-004
def test_offline_timeout_retryable():
    b = ScriptBackend({("sonnet", "factcheck"): BackendError("x", reason="offline")})
    c1 = check_claim(b, "sonnet", CLAIM, "", "en")
    b.handlers[("sonnet", "factcheck")] = BackendError("x", reason="timeout")
    c2 = check_claim(b, "sonnet", dict(CLAIM, id="C02"), "", "en")
    assert (c1["status"], c1["reason"]) == ("cannot_verify", "offline")
    assert (c2["status"], c2["reason"]) == ("cannot_verify", "timeout")
    assert is_retryable(c1) and is_retryable(c2)


# @S-factcheck-ledger-005
def test_continue_checks_only_retryable(tmp_path):
    run = make_run(tmp_path)
    write_ledger(run, [dict(CLAIM, id="C01", status="supported"),
                       dict(CLAIM, id="C02", status="cannot_verify", reason="offline"),
                       dict(CLAIM, id="C03", status="cannot_verify", reason="no_source")])
    b = ScriptBackend({("sonnet", "factcheck"): search_result("supported", ["https://a.example"],
                                                              ["https://a.example"])})
    run_checks(run, b, "sonnet", "en", say=lambda *_: None)
    assert len(b.calls) == 1 and "C02" not in b.calls[0]["prompt"]  # prompt has claim text
    assert [c["status"] for c in read_ledger(run)] == ["supported", "supported", "cannot_verify"]


def _setup_reported(tmp_path, ledger):
    run = make_run(tmp_path)
    for m in ("opus", "sonnet"):
        write_json(run.path(f"03-reviews/{m}.json"), ok(m, review_data(flags=["hallucination"]
                                                                       if m == "opus" else [])))
    write_ledger(run, ledger)
    cons = compute_consensus(run, ["opus", "sonnet"], TH)
    write_report(run, cons, lang="en")
    return run


# @S-factcheck-ledger-006
def test_unfinished_continue_offers_choices(tmp_path):
    led = [dict(CLAIM, id=f"C{i:02d}", status="supported") for i in range(1, 19)]
    led += [dict(CLAIM, id=f"C{i:02d}", status="pending") for i in range(19, 31)]
    run = _setup_reported(tmp_path, led)
    fails = iter([BackendError("x", reason="offline")] * 9 + [BackendError("x", reason="timeout")] * 3)
    b = ScriptBackend({("*", "factcheck"): lambda p: next(fails)})
    io = ScriptedIO(["1"])
    assert factcheck_continue(run, b, ["opus", "sonnet"], TH, "en", io) == "later"
    assert "18/30" in io.text and "offline 9" in io.text and "timeout 3" in io.text
    assert "Continue another time" in io.text and "Stop and finalize" in io.text
    assert f"factcheck {run.id} --continue" in io.text


# @S-factcheck-ledger-007
def test_finalize_unchanged(tmp_path):
    run = _setup_reported(tmp_path, [dict(CLAIM, status="cannot_verify", reason="no_source")])
    io = ScriptedIO([])
    assert factcheck_continue(run, ScriptBackend(), ["opus", "sonnet"], TH, "en", io) == "unchanged"
    assert "unchanged" in io.text and latest_version(run) == 1


# @S-factcheck-ledger-008
def test_finalize_changed_writes_v2(tmp_path):
    run = _setup_reported(tmp_path, [dict(CLAIM, id="C02", status="cannot_verify", reason="offline")])
    b = ScriptBackend({("*", "factcheck"): search_result("unsupported", ["https://a.example/n"],
                                                         ["https://a.example/n"])})
    io = ScriptedIO([])
    assert factcheck_continue(run, b, ["opus", "sonnet"], TH, "en", io) == "updated"
    assert [c["task"] for c in b.calls] == ["factcheck"]
    md = run.path("06-report.v2.md").read_text()
    assert "C02: cannot_verify -> unsupported" in md
    assert "red line hallucination: needs_ruling -> confirmed" in md


# @S-factcheck-ledger-009
def test_s_curve_claim():
    reviews = {m: ok(m, review_data(stage="growth")) for m in ("opus", "sonnet")}
    sc = [c for c in build_ledger(reviews, [], ["opus", "sonnet"]) if c["id"] == "SC1"][0]
    assert sc["type"] == "s_curve_stage" and sc["stage"] == "growth" and "growth" in sc["text"]


def test_snapshot_changes_with_status():
    a = [dict(CLAIM)]
    b = [dict(CLAIM, status="supported")]
    assert snapshot(a) != snapshot(b)

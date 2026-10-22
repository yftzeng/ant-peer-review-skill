from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.revision import char_diff, run_revision
from helpers import ScriptBackend, make_run, ok, review_data

TEXT = "# 標題\n\n我們的產品很棒棒，大家都喜翻。\n\nSecond para here."


def cons_with(*findings):
    fs = []
    for i, (level, sev) in enumerate(findings, 1):
        fs.append({"id": f"F{i:02d}", "anchor": "D1.P02.S1", "level": level, "severity": sev,
                   "observation": f"obs{i}", "standard": "s", "why_it_matters": "w",
                   "action": "a", "label": "SINGLE", "supporters": ["opus"], "dissent": [],
                   "members": ["opus:I1"], "dimension": "micro"})
    return {"findings": fs, "unverified_findings": []}


def setup(tmp_path, cons):
    run = make_run(tmp_path, text=TEXT)
    for m in ("opus", "sonnet"):
        write_json(run.path(f"03-reviews/{m}.json"), ok(m, review_data()))
    write_json(run.path("05-consensus.json"), cons)
    return run


A_OUT = {"paragraphs": [{"id": "D1.P02", "text": "我們的產品很棒，大家都喜歡。"}],
         "corrections": [{"from": "喜翻", "to": "喜歡", "category": "typo"}]}
B_OUT = {"headline_options": ["H"], "paragraphs": [{"id": "D1.P03", "text": "Rewritten.",
                                                    "addresses": ["F01"]}], "notes": ""}
RR = {"verdicts": [{"issue": "F01", "verdict": "RESOLVED", "note": ""}]}


# @S-revision-001
# @N-revision-001
def test_char_diff_and_full_text(tmp_path):
    assert char_diff("很棒棒", "很棒") == "很棒[-棒-]"
    run = setup(tmp_path, cons_with(("micro", "minor")))
    b = ScriptBackend({("opus", "revise_a"): A_OUT})
    run_revision(run, b, ["opus", "sonnet"], "en", say=lambda *_: None)
    diff = run.path("07-revision/A.diff").read_text()
    assert "@@ D1.P02 @@" in diff and "很棒[-棒-]" in diff and "喜[-翻-]{+歡+}" in diff
    a = run.path("07-revision/A.md").read_text()
    assert a.startswith("# 標題\n\n我們的產品很棒，大家都喜歡。") and "Second para here." in a


# @S-revision-002
def test_a_gets_micro_b_gets_macro_meso(tmp_path):
    run = setup(tmp_path, cons_with(("macro", "major"), ("meso", "major"), ("micro", "minor")))
    b = ScriptBackend({("opus", "revise_a"): A_OUT, ("opus", "revise_b"): B_OUT,
                       ("sonnet", "rereview"): RR})
    run_revision(run, b, ["opus", "sonnet"], "en", say=lambda *_: None)
    pa = [c for c in b.calls if c["task"] == "revise_a"][0]["prompt"]
    pb = [c for c in b.calls if c["task"] == "revise_b"][0]["prompt"]
    assert "obs3" in pa and "obs1" not in pa and "obs2" not in pa
    assert "obs1" in pb and "obs2" in pb and "obs3" not in pb


# @S-revision-003
def test_b_rereviewed_by_other_model(tmp_path):
    run = setup(tmp_path, cons_with(("macro", "major")))
    b = ScriptBackend({("opus", "revise_a"): A_OUT, ("opus", "revise_b"): B_OUT,
                       ("sonnet", "rereview"): RR})
    run_revision(run, b, ["opus", "sonnet"], "en", say=lambda *_: None)
    rr = read_json(run.path("07-revision/rereview.json"))
    assert rr["checker"] == "sonnet" and rr["verdicts"][0]["verdict"] == "RESOLVED"
    assert [c["model"] for c in b.calls if c["task"] == "rereview"] == ["sonnet"]


# @S-revision-004
def test_unknown_ids_ignored(tmp_path):
    run = setup(tmp_path, cons_with(("micro", "minor")))
    b = ScriptBackend({("opus", "revise_a"): {"paragraphs": [{"id": "D9.P99", "text": "x"}],
                                              "corrections": []}})
    out = run_revision(run, b, ["opus", "sonnet"], "en", say=lambda *_: None)
    assert any("D9.P99" in w for w in out["warnings"])
    assert "我們的產品很棒棒" in run.path("07-revision/A.md").read_text()


# @S-revision-005
def test_no_b_without_macro_meso(tmp_path):
    run = setup(tmp_path, cons_with(("micro", "minor")))
    b = ScriptBackend({("opus", "revise_a"): A_OUT})
    out = run_revision(run, b, ["opus", "sonnet"], "en", say=lambda *_: None)
    assert [c["task"] for c in b.calls] == ["revise_a"]
    assert any("plan B skipped" in n for n in out["notes"])
    assert not run.path("07-revision/B.md").exists()


# @S-revision-006
def test_sentence_ids_and_inserts(tmp_path):
    from ant_peer_review.revision import apply_changes, paragraphs, render_text
    run = make_run(tmp_path, text="# T\n\nOld one. Keep two.\n\nLast para.")
    paras = paragraphs(run)
    rep, warn = apply_changes(paras, [{"id": "D1.P02.S1", "text": "New one."},
                                      {"id": "D1.P02+", "text": "Inserted para."}])
    assert warn == []
    assert render_text(paras, rep) == "# T\n\nNew one. Keep two.\n\nInserted para.\n\nLast para.\n"

"""D-0002: long targets reviewed in parts, then one series-level pass."""
import re

from ant_peer_review.backends.base import Result
from ant_peer_review.jsonio import read_json
from ant_peer_review.refresh import compute_consensus
from ant_peer_review.report import latest_version, write_report
from ant_peer_review.review import run_debate, run_round1
from helpers import DIMS, ScriptBackend, make_run, review_data

TH = {"excellent": 85, "good": 70, "revise": 60}
M = ["opus", "sonnet"]


def series(n=12, words=900):
    body = lambda k: "\n\n".join(f"Body of article {k} sentence {j} " + "word " * words for j in range(2))
    return "# Series\n\nIntro.\n\n\n" + "".join(
        f"---\n## Day {k}｜Title {k}\nhttps://blog.example/a/{k}  (2026-08-{k:02d} 10:00:00)\n\n{body(k)}\n\n"
        for k in range(1, n + 1))


def first_id(prompt):
    return re.search(r"\[(D[\w-]+\.P\d+\.S\d+)\]", prompt).group(1)


def review_for(prompt):
    a = first_id(prompt)
    score = 50 if "[D1-11." in prompt else 80
    return review_data(scores=(80, score, 90, 60), issues=[{"anchor": a, "claim_ids": ["K1"]}],
                       claims=[{"anchor": a}])


REDUCE = {"orientation": "The whole series.", "macro": {"score": 66, "rationale": "arc is uneven"},
          "issues": [{"id": "I1", "anchor": "missing: D1-12 - a closing summary; searched: all parts",
                      "level": "macro", "dimension": "macro", "observation": "no wrap-up",
                      "standard": "s", "why_it_matters": "w", "action": "a", "severity": "minor",
                      "claim_ids": []}]}


# @S-review-panel-031
def test_long_target_is_reviewed_in_parts_then_once_for_the_series(tmp_path):
    run = make_run(tmp_path, text=series())
    b = ScriptBackend({("*", "review"): review_for, ("*", "review_reduce"): REDUCE})
    recs = run_round1(run, b, M, "en", say=lambda *_: None)
    reviews = [c for c in b.calls if c["task"] == "review"]
    assert len(reviews) == 6 and [c["task"] for c in b.calls].count("review_reduce") == 2
    parts = sorted({tuple(sorted({i.split(".")[0] for i in re.findall(r"\[(D[\w-]+)\.P", c["prompt"])}))
                    for c in reviews})
    assert [len(p) for p in sorted(parts, key=lambda p: int(p[0].split("-")[1]))] == [5, 5, 2]
    assert "part 1 of 3" in reviews[0]["prompt"]
    red = next(c for c in b.calls if c["task"] == "review_reduce")["prompt"]
    assert "Body of article" not in red and "obs" in red
    data = recs["opus"]["data"]
    by = {s["dimension"]: s["score"] for s in data["scores"]}
    chars = read_json(run.path("03-reviews/opus.json"))["mapreduce"]["parts"]
    w = sum(p["chars"] for p in chars)
    want = round(sum(p["chars"] * (50 if "D1-11" in p["docs"] else 80) for p in chars) / w, 1)
    assert by["macro"] == 66 and round(by[DIMS[1]], 1) == want
    ids = [i["id"] for i in data["issues"]]
    assert {"G1-I1", "G2-I1", "G3-I1", "S-I1"} == set(ids)
    assert data["issues"][0]["claim_ids"] == ["G1-K1"] and data["claims"][0]["id"] == "G1-K1"
    short = make_run(tmp_path / "short")
    b2 = ScriptBackend({("*", "review"): review_data()})
    run_round1(short, b2, M, "en", say=lambda *_: None)
    assert [c["task"] for c in b2.calls] == ["review", "review"]


def refusing(prompt):
    if "part " not in prompt or "[D1-7." in prompt:
        return Result(model="", model_id="", data=None, refused=True, refusal_detail="policy")
    return review_for(prompt)


# @S-review-panel-032
def test_a_refusal_loses_only_what_was_refused(tmp_path):
    run = make_run(tmp_path, text=series())
    b = ScriptBackend({("opus", "review"): review_for, ("sonnet", "review"): refusing,
                       ("*", "review_reduce"): REDUCE})
    recs = run_round1(run, b, M, "en", say=lambda *_: None)
    assert recs["sonnet"]["status"] == "ok"
    skipped = recs["sonnet"]["mapreduce"]["skipped"]
    assert [s["doc"] for s in skipped] == ["D1-7"] and skipped[0]["title"] == "Day 7｜Title 7"
    assert skipped[0]["url"] == "https://blog.example/a/7"
    cons = compute_consensus(run, M, TH)
    assert [s["doc"] for s in cons["skipped_docs"]] == ["D1-7"] and cons["partial"] is True
    write_report(run, cons, lang="en")
    md = run.path(f"06-report.v{latest_version(run)}.md").read_text()
    assert "provisional" in md.lower() and "Day 7｜Title 7" in md
    from ant_peer_review.deliver import render_review
    from ant_peer_review.i18n import T
    assert "Day 7｜Title 7" in render_review(run, cons, T("en"), TH, None)
    run2 = make_run(tmp_path / "most", text=series())
    most = lambda p: review_for(p) if ("part " in p and "[D1-1." in p and "[D1-2." not in p) else \
        Result(model="", model_id="", data=None, refused=True, refusal_detail="policy")
    b2 = ScriptBackend({("opus", "review"): review_for, ("sonnet", "review"): most,
                        ("*", "review_reduce"): REDUCE})
    assert run_round1(run2, b2, M, "en", say=lambda *_: None)["sonnet"]["status"] == "refused"


# @S-review-panel-033
def test_debate_after_parts_sees_only_anchored_paragraphs(tmp_path):
    run = make_run(tmp_path, text=series())
    b = ScriptBackend({("*", "review"): review_for, ("*", "review_reduce"): REDUCE,
                       ("*", "debate"): {"responses": []}})
    run_round1(run, b, M, "en", say=lambda *_: None)
    run_debate(run, b, M, "en", say=lambda *_: None)
    d = next(c for c in b.calls if c["task"] == "debate")["prompt"]
    assert "[D1-1.P01" in d and "[D1-11.P01" in d and "[D1-4.P01" not in d

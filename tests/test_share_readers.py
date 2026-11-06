"""S-share-019..024: the reader mix, the reader review loop and the analysis fixes."""
import pytest

from ant_peer_review import readers
from ant_peer_review.backends.base import BackendError
from ant_peer_review.jsonio import append_jsonl, read_json
from ant_peer_review.share import DISTILL_RULES, dropped_numbers
from ant_peer_review.ui import ScriptedIO
from helpers import ScriptBackend
from test_share import ANALYSIS, SUMMARY, URL, decide, distill_run, posts, share_run

MIX = {"weights": {"public": 25, "beginner": 30, "expert": 30, "business": 15},
       "why": {"public": "hook", "beginner": "usable rule", "expert": "tension", "business": "attitude"},
       "basis": {"stage": "tipping point, unchecked", "maturity": "preprint", "media": "light"}}
POST = f"Revenue grew 40% in 2025, says Title. A skipped step looked done and was wrong: {URL}"
NEW = f"Revenue grew 40% in 2025, says Title. Ask before an agent skips a step: {URL}"


def report(prompt, verdict="met"):
    keys = [k for k in ("x-summary", "x-insight", "instagram-insight") if f"Post {k}" in prompt]
    return {"reports": [{"key": k, "verdict": verdict, "hook": "前兩行有畫面", "peak": "其實是錯的",
                         "stuck": "", "takeaway": "先講好再偏離", "would": "按讚", "would_not": "",
                         "reason": "看得懂"} for k in keys]}


def sc1(run, text="The topic of this piece is at the 'tipping_point' stage of its adoption S-curve. "
                  "Suggested evidence search: AI 代理 2026", status="unsupported"):
    append_jsonl(run.path("factcheck/ledger.jsonl"), {
        "id": "SC1", "anchor": "D1", "type": "s_curve_stage", "stage": "tipping_point", "text": text,
        "status": status, "reason": "no adoption data", "sources": [], "refs": [], "checked_by": "sonnet"})


def handlers(**extra):
    h = {("*", "summary"): SUMMARY, ("*", "judge"): {"verdicts": []},
         ("*", "share"): posts(x_summary=POST), ("*", "readers_mix"): MIX, ("*", "reader"): report}
    h.update({("*", k): v for k, v in extra.items()})
    return h


# @S-share-019
def test_reader_mix_is_proposed_from_the_stage_and_confirmed(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    sc1(run)
    b = ScriptBackend(handlers())
    io = ScriptedIO(["2", "public=10,beginner=40,expert=40,business=10"])   # edit, then type the mix
    decide(run, store, b, io=io)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("readers_mix") == 1 and tasks.index("readers_mix") < tasks.index("share")
    mp = b.calls[tasks.index("readers_mix")]["prompt"]
    assert "tipping_point" in mp and "unsupported" in mp
    shown = "\n".join(io.out)
    assert "25" in shown and "usable rule" in shown and "preprint" in shown
    mix = read_json(run.path("readers.json"))
    assert mix["weights"] == {"public": 10, "beginner": 40, "expert": 40, "business": 10}
    assert mix["set_by"] == "user" and mix["why"]["expert"] == "tension"


# @S-share-019
def test_without_a_person_the_proposal_is_used_unless_readers_are_given(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    decide(run, store, ScriptBackend(handlers()))
    assert read_json(run.path("readers.json"))["set_by"] == "proposal"
    run2, store2 = share_run(tmp_path / "b", ["x"], {"x": ["summary"]})
    b = ScriptBackend(handlers())
    readers.ensure_mix(run2, b, ["opus", "sonnet"], "en",
                       spec="public=40,beginner=20,expert=20,business=20")
    assert "readers_mix" not in [c["task"] for c in b.calls]
    assert read_json(run2.path("readers.json"))["weights"]["public"] == 40


# @S-share-019
@pytest.mark.parametrize("spec", ["public=50,beginner=30,expert=30,business=15",
                                  "public=25,beginner=30,expert=30,boss=15", "public=x"])
def test_a_bad_reader_mix_is_a_usage_error(spec):
    with pytest.raises(ValueError):
        readers.parse_mix(spec)


# @S-share-019
def test_a_failed_mix_call_gives_equal_weights_and_says_so(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    decide(run, store, ScriptBackend(handlers(readers_mix=BackendError("down"))))
    mix = read_json(run.path("readers.json"))
    assert mix["weights"] == {"public": 25, "beginner": 25, "expert": 25, "business": 25}
    assert mix["set_by"] == "fallback"


# @S-share-020
def test_each_reader_sees_only_the_posts_and_its_own_goal(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    b = ScriptBackend(handlers())
    decide(run, store, b)
    calls = [c for c in b.calls if c["task"] == "reader"]
    assert len(calls) == 4
    for persona in readers.PERSONAS:
        mine = [c for c in calls if readers.GOALS[persona] in c["prompt"]]
        assert len(mine) == 1, persona
        p = mine[0]["prompt"]
        assert f"weight {MIX['weights'][persona]}%" in p and POST in p
        assert "First para." not in p                                    # not the article
        assert all(readers.GOALS[o] not in p for o in readers.PERSONAS if o != persona)
    fields = set(readers.READER_SCHEMA["properties"]["reports"]["items"]["properties"])
    assert fields == {"key", "verdict", "hook", "peak", "stuck", "takeaway", "would", "would_not",
                      "reason"}


def revise_with(text):
    return {"posts": [{"key": "x-summary", "text": text, "rulings": [
        {"reader": "public", "point": "術語太多", "ruling": "accept", "why": "刪掉三個名詞"},
        {"reader": "expert", "point": "想反駁門檻", "ruling": "reject", "why": "這是他要留言的點"}]}]}


# @S-share-021
def test_the_writer_rules_and_the_revision_passes_the_gate_before_readers_see_it(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    seen = []

    def reader(prompt):
        seen.append(prompt)
        first = len(seen) <= 4
        return report(prompt, "partly" if first and "expert" not in prompt.split("\n")[0] else "met")

    b = ScriptBackend(handlers(reader=reader, reader_revise=revise_with(NEW)))
    decide(run, store, b)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("reader") == 8 and tasks.count("reader_revise") == 1
    rv = tasks.index("reader_revise")
    assert "judge" in tasks[rv:tasks.index("reader", rv)]          # gate between revise and reread
    assert all(NEW in p for p in seen[4:])
    assert NEW in run.path("share-x-summary.md").read_text()
    md = run.path("readers.md").read_text()
    for want in ("25%", "usable rule", "partly", "met", "刪掉三個名詞", "reject", "這是他要留言的點"):
        assert want in md, want
    ask = b.calls[rv]["prompt"]
    assert "weight 30%" in ask and "看得懂" in ask and POST in ask


# @S-share-021
def test_at_most_two_reader_rounds_and_the_last_revision_is_gated(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    revs = iter([revise_with(NEW), revise_with(NEW.replace("Ask", "Last: ask"))])
    b = ScriptBackend(handlers(reader=lambda p: report(p, "partly"),
                               reader_revise=lambda p: next(revs)))
    decide(run, store, b)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("reader") == 8 and tasks.count("reader_revise") == 2
    assert "judge" in tasks[len(tasks) - 1 - tasks[::-1].index("reader_revise"):]
    assert "Last: ask" in run.path("share-x-summary.md").read_text()


# @S-share-021
def test_when_every_reader_says_met_nothing_is_revised(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    b = ScriptBackend(handlers())
    decide(run, store, b)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("reader") == 4 and "reader_revise" not in tasks
    assert POST in run.path("share-x-summary.md").read_text()


# @S-share-022
def test_invented_experience_fails_even_with_a_take(tmp_path):
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]},
                           take="focus on the sentence about normal things")
    bad = "我現在給 AI 代理的指示會多加這段"
    judged = []

    def judge(prompt):
        judged.append(prompt)
        if bad in prompt:
            return {"verdicts": [{"key": "x-summary", "checks": [
                {"name": "invented_experience", "pass": False, "evidence": bad}]}]}
        return {"verdicts": []}

    b = ScriptBackend(handlers(share=posts(x_summary=f"{bad}。{POST}"), judge=judge,
                               share_rewrite=posts(x_summary=POST)))
    decide(run, store, b)
    j = [c for c in b.calls if c["task"] == "judge"][0]
    assert "invented_experience" in j["system"] and "focus on the sentence" in j["prompt"]
    ask = [c for c in b.calls if c["task"] == "share_rewrite"][0]["prompt"]
    assert "judge:invented_experience" in ask
    assert bad not in run.path("share-x-summary.md").read_text()


# @S-share-023
def test_the_analysis_leaves_out_the_s_curve_check(tmp_path):
    run, store = distill_run(tmp_path)
    sc1(run)
    b = ScriptBackend(handlers(share_analysis=ANALYSIS,
                               share=posts(x_insight="流程越短，出錯越少。", instagram_insight="交接本身就是風險。")))
    decide(run, store, b)
    ap = [c for c in b.calls if c["task"] == "share_analysis"][0]["prompt"]
    assert "S-curve" not in ap
    a = read_json(run.path("share-analysis.json"))
    assert all("SC1" not in r["ids"] for r in a["claims"])
    assert "2026" not in dropped_numbers(a)


# @S-share-023
def test_an_empty_analysis_is_asked_again_then_fails(tmp_path):
    run, store = distill_run(tmp_path)
    empty = dict(ANALYSIS, purpose="", thesis="", anchors=[], claims=[])
    b = ScriptBackend(handlers(share_analysis=empty))
    decide(run, store, b)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("share_analysis") == 2 and "share" not in tasks
    assert not list(run.root.glob("share-x-*.md"))


# @S-share-023
def test_a_refused_analysis_says_why(tmp_path):
    import json as _json
    from ant_peer_review.backends.base import BackendError, Result
    from ant_peer_review.backends.claude_cli import parse_output
    from ant_peer_review.i18n import T
    from ant_peer_review.share import analyse_article
    final = {"type": "result", "stop_reason": "tool_use", "safety_stops": 2, "is_error": False,
             "result": '{"purpose":"half"}', "structured_output": dict(ANALYSIS)}
    res = parse_output(_json.dumps(final), streamed=False)
    assert res.refused and res.data is None and "safety classifier" in res.refusal_detail
    assert not parse_output(_json.dumps(dict(final, safety_stops=0)), streamed=False).refused
    run, store = distill_run(tmp_path)
    decide(run, store, ScriptBackend(handlers(share_analysis=ANALYSIS, share=posts(x_insight="流程越短，出錯越少。"))))
    refused = Result(model="", model_id="", data=None, refused=True, refusal_detail=res.refusal_detail)
    with pytest.raises(BackendError, match="refused: stopped by the safety classifier"):
        analyse_article(run, ScriptBackend({("*", "share_analysis"): refused}), "opus",
                        read_json(run.path("05-consensus.json")), "", "zh-TW", T("zh-TW"))


# @S-share-024
def test_a_distilled_post_names_its_subject_in_the_output_language():
    assert "term the checked claims use" in DISTILL_RULES
    assert "takeaway and the hook in the opening lines" in DISTILL_RULES
    assert "background a reader needs before the take" not in DISTILL_RULES
    assert "evidence in order of importance; background last" in DISTILL_RULES


# @S-share-021
def test_readers_read_the_post_with_its_source_line_and_length_is_no_defect(tmp_path):
    run, store = distill_run(tmp_path)
    b = ScriptBackend(handlers(share_analysis=ANALYSIS,
                               share=posts(x_insight="流程越短，出錯越少。", instagram_insight="交接本身就是風險。")))
    decide(run, store, b)
    p = [c for c in b.calls if c["task"] == "reader"][0]["prompt"]
    assert "延伸自：Title https://ex.example/a" in p and "延伸自：Title\n" in p
    assert "length is no defect" in readers.REVISE_RULES.lower()
    assert "moves up" in readers.REVISE_RULES and "dropped before any is explained" in readers.REVISE_RULES


# @S-share-019
def test_a_mix_given_with_readers_says_set_by_you(tmp_path):
    from ant_peer_review.i18n import T
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    readers.ensure_mix(run, ScriptBackend(handlers()), ["opus", "sonnet"], "en",
                       spec="public=25,beginner=30,expert=30,business=15")
    md = readers.readers_md(T("en"), read_json(run.path("readers.json")), [])
    assert "set by you" in md.lower() and "— —" not in md


# @S-share-025
@pytest.mark.parametrize("reply", [{"posts": []}, "refused"])
def test_a_writer_that_returns_no_post_fails_out_loud(tmp_path, reply):
    from ant_peer_review.backends.base import Result
    from ant_peer_review.deliver import deliver
    from test_decision import M, TH
    run, store = share_run(tmp_path, ["x"], {"x": ["summary"]})
    out = Result(model="opus", model_id="x", data=None, refused=True) if reply == "refused" else reply
    b = ScriptBackend(handlers(share=out))
    said = []
    deliver(run, b, M, "en", TH, [], say=said.append, home=store.home)
    tasks = [c["task"] for c in b.calls]
    assert tasks.count("share") == 2 and "reader" not in tasks
    assert any("✗" in s and "no post" in s for s in said)
    assert any("refus" in s for s in said) == (reply == "refused")

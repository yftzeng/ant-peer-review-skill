import json

from ant_peer_review.i18n import T
from ant_peer_review.intake import build_intake_from_args, run_intake_interactive
from ant_peer_review.jsonio import read_json, write_json
from ant_peer_review.sources.crawler import FetchError, FetchResult
from ant_peer_review.ui import ScriptedIO
from helpers import ScriptBackend, make_run

TEXT = ("# Cited\n\nThermometry was shown in doi:10.1038/nature12373 last year. "
        "A fake one: https://doi.org/10.9999/not-real. "
        "Transformers came from arXiv:1706.03762.\n\n"
        "The retracted study 10.1016/S0140-6736(97)11096-0 is still quoted. "
        "See “A Totally Different Paper Title About Cats” at 10.1000/mismatch.")

CROSSREF = {
    "10.1038/nature12373": {"title": ["Nanometre-scale thermometry in a living cell"],
                            "issued": {"date-parts": [[2013, 7, 31]]}},
    "10.1016/S0140-6736(97)11096-0": {
        "title": ["RETRACTED: Ileal-lymphoid-nodular hyperplasia"],
        "issued": {"date-parts": [[1998]]},
        "updated-by": [{"type": "retraction", "DOI": "10.1016/s0140-6736(10)60175-4"}]},
    "10.1000/mismatch": {"title": ["Quantum Effects in Superconducting Rings"],
                         "issued": {"date-parts": [[2020]]}},
}
ATOM_OK = ("<feed xmlns='http://www.w3.org/2005/Atom'><title>q</title><entry><id>x</id>"
           "<title>Attention Is All You Need</title><published>2017-06-12T17:57:34Z</published>"
           "</entry></feed>")
ATOM_EMPTY = "<feed xmlns='http://www.w3.org/2005/Atom'><title>q</title></feed>"
ATOM_ERROR = ("<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Error</title>"
              "<summary>incorrect id format</summary></entry></feed>")


class Api:
    def __init__(self, arxiv=ATOM_OK):
        self.calls, self.arxiv = [], arxiv

    def fetch(self, url):
        from urllib.parse import unquote
        self.calls.append(url)
        if "doi.org/api/handles/" in url:
            doi = unquote(url.split("/api/handles/")[1])
            if doi.startswith("10.9999"):
                raise FetchError("http_status", "404")
            body = {"responseCode": 1, "handle": doi}
            return FetchResult(url, url, 200, "application/json", json.dumps(body).encode(), [url])
        if "api.crossref.org/works/" in url:
            doi = unquote(url.split("/works/")[1].split("?")[0])
            if doi not in CROSSREF:
                raise FetchError("http_status", "404")
            body = {"status": "ok", "message": CROSSREF[doi]}
            return FetchResult(url, url, 200, "application/json", json.dumps(body).encode(), [url])
        if "export.arxiv.org" in url:
            return FetchResult(url, url, 200, "application/atom+xml", self.arxiv.encode(), [url])
        raise AssertionError(url)


def setup(tmp_path, sources):
    run = make_run(tmp_path, text=TEXT)
    intake = read_json(run.path("00-intake.json"))
    intake["fact_sources"] = sources
    write_json(run.path("00-intake.json"), intake)
    return run


# @S-intake-009
def test_fact_source_checkbox_after_audience():
    t = T("en")
    io = ScriptedIO(["1", "some text", "/done", "", "", "", "", "", "1", "1", ""])
    intake = run_intake_interactive(io, t, "en")
    assert intake["fact_sources"] == ["academic"]
    assert "[ ] Academic identifiers" in io.text
    io = ScriptedIO(["1", "some text", "/done", "", "", "", "", "", "1", ""])
    assert run_intake_interactive(io, t, "en")["fact_sources"] == []
    assert build_intake_from_args("audit", ["x"], None, lang="en", academic=True)["fact_sources"] \
        == ["academic"]


# @S-factcheck-ledger-012
def test_off_by_default_no_requests(tmp_path):
    from ant_peer_review.scholarly import verify_identifiers
    run = setup(tmp_path, [])
    api = Api()
    assert verify_identifiers(run, api) == []
    assert api.calls == []


# @S-factcheck-ledger-013
def test_identifiers_verified(tmp_path):
    from ant_peer_review.factcheck import read_ledger, run_checks
    from ant_peer_review.scholarly import verify_identifiers
    run = setup(tmp_path, ["academic"])
    verify_identifiers(run, Api())
    led = {c["ident"]: c for c in read_ledger(run) if c["type"] == "citation"}
    ok = led["10.1038/nature12373"]
    assert ok["status"] == "supported" and "Nanometre-scale thermometry" in ok["sources"][0]["supporting_excerpt"]
    assert "2013" in ok["sources"][0]["supporting_excerpt"]
    assert ok["sources"][0]["url"] == "https://doi.org/10.1038/nature12373" and ok["sources"][0]["accessed_at"]
    assert (led["10.9999/not-real"]["status"], led["10.9999/not-real"]["reason"]) == \
        ("unsupported", "identifier_not_found")
    ax = led["arXiv:1706.03762"]
    assert ax["status"] == "supported" and "Attention Is All You Need" in ax["sources"][0]["supporting_excerpt"]
    assert ax["sources"][0]["url"] == "https://arxiv.org/abs/1706.03762"
    assert ok["anchor"].startswith("D1.P02")
    b = ScriptBackend()
    run_checks(run, b, "sonnet", "en", say=lambda *_: None)
    assert all("nature12373" not in c["prompt"] for c in b.calls)


# @S-factcheck-ledger-014
def test_retraction_and_title_mismatch(tmp_path):
    from ant_peer_review.factcheck import read_ledger
    from ant_peer_review.scholarly import verify_identifiers
    run = setup(tmp_path, ["academic"])
    verify_identifiers(run, Api())
    led = {c["ident"]: c for c in read_ledger(run) if c["type"] == "citation"}
    r = led["10.1016/S0140-6736(97)11096-0"]
    assert (r["status"], r["reason"]) == ("unsupported", "retracted")
    m = led["10.1000/mismatch"]
    assert (m["status"], m["reason"]) == ("partly", "title_mismatch")


# @S-factcheck-ledger-015
def test_arxiv_not_found_shapes(tmp_path):
    from ant_peer_review.factcheck import read_ledger
    from ant_peer_review.scholarly import verify_identifiers
    for body in (ATOM_EMPTY, ATOM_ERROR):
        run = setup(tmp_path / body[:10].replace("<", "x"), ["academic"])
        verify_identifiers(run, Api(arxiv=body))
        ax = [c for c in read_ledger(run) if c.get("ident") == "arXiv:1706.03762"][0]
        assert (ax["status"], ax["reason"]) == ("unsupported", "identifier_not_found")

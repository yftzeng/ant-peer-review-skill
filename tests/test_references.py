"""docs/REFERENCES.md pins every GitHub reference; scripts/refs-drift.sh checks upstream."""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIFT = ROOT / "scripts" / "refs-drift.sh"
PIN = re.compile(r"https://github\.com/[^/\s)]+/[^/\s)]+/(?:tree|blob)/([0-9a-f]{40})(?=[/)\s]|$)")


# @S-references-001
def test_github_references_are_pinned():
    refs = (ROOT / "docs" / "REFERENCES.md").read_text()
    urls = re.findall(r"https?://github\.com/[^\s)>`\"]*", refs)
    assert urls
    for url in urls:
        assert PIN.match(url), url
    links = re.findall(r"\[([^\]]*)\]\((https://github\.com/[^)\s]+)\)", refs)
    shorts = 0
    for text, url in links:
        short = re.search(r"@([0-9a-f]{7,40})\b", text)
        if short:
            shorts += 1
            assert PIN.match(url).group(1).startswith(short.group(1)), text
    assert shorts == len(links)
    assert re.search(r"^Upstream last checked: \d{4}-\d{2}-\d{2}\b", refs, re.M)


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def _upstream(tmp_path, change_b):
    work = tmp_path / "work"
    for f in ("a/x.md", "b/y.md"):
        (work / f).parent.mkdir(parents=True, exist_ok=True)
        (work / f).write_text("one\n")
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "one")
    pin = _git(work, "rev-parse", "HEAD")
    if change_b:
        (work / "b" / "y.md").write_text("two\n")
        (work / "c.md").write_text("new\n")
        _git(work, "add", ".")
        _git(work, "commit", "-q", "-m", "two")
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(tmp_path / "base" / "o" / "r"))
    return pin, _git(work, "rev-parse", "HEAD")


def _drift(tmp_path, pin, repo="r"):
    refs = tmp_path / "REFERENCES.md"
    refs.write_text(
        f"| 1 | [o/{repo} — a @{pin[:7]}](https://github.com/o/{repo}/tree/{pin}/a) |\n"
        f"| 2 | [o/{repo} — b @{pin[:7]}](https://github.com/o/{repo}/blob/{pin}/b/y.md) |\n"
        "Upstream last checked: 2026-10-24\n")
    before = refs.read_bytes()
    env = {**os.environ, "REFS_GIT_BASE": f"file://{tmp_path / 'base'}"}
    r = subprocess.run(["bash", str(DRIFT), str(refs)], env=env, capture_output=True, text=True)
    assert refs.read_bytes() == before  # @N-references-001
    return r, r.stdout.strip().splitlines()


# @S-references-002
def test_drift_reports_the_changed_path(tmp_path):
    pin, head = _upstream(tmp_path, change_b=True)
    r, lines = _drift(tmp_path, pin)
    out = "\n".join(lines)
    assert r.returncode == 1, out
    assert lines[-1].startswith("refs-drift: CHANGED"), out
    a = next(ln for ln in lines if ln.startswith("o/r a"))
    assert "moved, path unchanged" in a
    b = next(ln for ln in lines if ln.startswith("o/r b/y.md"))
    assert "CHANGED" in b
    assert "M\tb/y.md" in out and "c.md" not in out
    assert f"https://github.com/o/r/compare/{pin[:12]}...{head[:12]}" in out


# @S-references-003
def test_drift_passes_when_unmoved_and_fails_when_unreadable(tmp_path):
    pin, head = _upstream(tmp_path, change_b=False)
    assert pin == head
    r, lines = _drift(tmp_path, pin)
    assert r.returncode == 0, lines
    assert lines[-1].startswith("refs-drift: PASS"), lines
    assert [ln for ln in lines if ln.startswith("o/r ")] and all(
        ln.endswith(" same") for ln in lines if ln.startswith("o/r "))
    r, lines = _drift(tmp_path, pin, repo="missing")
    assert r.returncode == 2, lines
    assert lines[-1].startswith("refs-drift: FAIL"), lines


MOVING = re.compile(r"https?://[^\s)>`\"]*/(?:current|latest|stable)(?:[/#?][^\s)>`\"]*)?(?=[\s)>`\"]|$)")


def unversioned_moving_links(text):
    return [ln for ln in text.splitlines()
            if MOVING.search(ln) and not re.search(r"\bv\d+(?:\.\d+)*\b", ln)]


# @S-references-004
def test_moving_links_name_the_version_read():
    assert unversioned_moving_links("[H, ch. 8](https://x.org/handbook/current/chapter-08)")
    assert not unversioned_moving_links("[H v6.5, ch. 8](https://x.org/handbook/current/chapter-08)")
    assert not unversioned_moving_links("[RFC](https://x.org/rfc/rfc7282.html) concurrent")
    refs = (ROOT / "docs" / "REFERENCES.md").read_text()
    assert unversioned_moving_links(refs) == []

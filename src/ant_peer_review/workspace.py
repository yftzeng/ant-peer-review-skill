"""Per-run workspace: folder layout, state.json, phase status and staleness."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .jsonio import read_json, sha256_file, write_bytes_atomic, write_json

PHASES = [
    "intake",
    "sources",
    "rubric",
    "review",
    "factcheck",
    "debate",
    "consensus",
    "report",
    "revision",
    "decision",
]

# Files (relative to the run folder) each phase reads. A directory entry hashes
# every file under it. Changing any of them makes the phase and its successors stale.
PHASE_INPUTS: dict[str, list[str]] = {
    "intake": [],
    "sources": ["00-intake.json"],
    "rubric": ["00-intake.json", "01-sources/manifest.json"],
    "review": ["02-rubric.json", "01-sources/normalized"],
    "factcheck": ["03-reviews"],
    "debate": ["03-reviews", "factcheck/ledger.jsonl"],
    "consensus": ["02-rubric.json", "03-reviews", "04-debate", "factcheck/ledger.jsonl"],
    "report": ["05-consensus.json"],
    "revision": ["05-consensus.json", "01-sources/normalized"],
    "decision": ["07-revision"],
}

PENDING, DONE, STALE, RUNNING = "pending", "done", "stale", "running"


def slugify(text: str, max_len: int = 40) -> str:
    norm = unicodedata.normalize("NFKC", text).lower()
    norm = re.sub(r"[^\w]+", "-", norm, flags=re.UNICODE).strip("-_")
    return (norm[:max_len].strip("-") or "run")


def _hash_input(root: Path, rel: str) -> dict[str, str]:
    p = root / rel
    if p.is_dir():
        return {
            str(f.relative_to(root)): sha256_file(f)
            for f in sorted(p.rglob("*"))
            if f.is_file() and not f.name.startswith(".")
        }
    if p.is_file():
        return {rel: sha256_file(p)}
    return {rel: "missing"}


@dataclass
class Run:
    root: Path

    @property
    def id(self) -> str:
        return self.root.name

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    # ---- state -----------------------------------------------------------
    def state(self) -> dict:
        return read_json(self.state_path)

    def save_state(self, state: dict) -> None:
        write_json(self.state_path, state)

    def settings(self) -> tuple[list[str], str, str]:
        """(models, backend, lang) recorded at creation; a resume always reuses them."""
        st = self.state()
        return list(st["models"]), st["backend"], st["lang"]

    def status(self, phase: str) -> str:
        return self.state()["phases"][phase]["status"]

    def input_hashes(self, phase: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for rel in PHASE_INPUTS[phase]:
            out.update(_hash_input(self.root, rel))
        return out

    def mark(self, phase: str, status: str, **extra) -> None:
        st = self.state()
        entry = st["phases"][phase]
        entry["status"] = status
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if status == DONE:
            entry["inputs"] = self.input_hashes(phase)
        entry.update(extra)
        self.save_state(st)

    def refresh(self) -> list[str]:
        """Re-hash inputs; a done phase whose inputs changed becomes stale with
        everything downstream. Returns the phases newly marked stale."""
        st = self.state()
        newly: list[str] = []
        cascade = False
        for ph in PHASES:
            entry = st["phases"][ph]
            if cascade:
                if entry["status"] == DONE:
                    entry["status"] = STALE
                    newly.append(ph)
                continue
            if entry["status"] == DONE and entry.get("inputs") != self.input_hashes(ph):
                entry["status"] = STALE
                newly.append(ph)
                cascade = True
            elif entry["status"] in (STALE, PENDING, RUNNING):
                # Anything after an unfinished phase cannot be trusted either.
                cascade = cascade or entry["status"] == STALE
        self.save_state(st)
        return newly

    def needs_run(self, phase: str) -> bool:
        self.refresh()
        return self.status(phase) != DONE

    def rerun_from(self, phase: str) -> None:
        st = self.state()
        idx = PHASES.index(phase)
        for ph in PHASES[idx:]:
            if st["phases"][ph]["status"] != PENDING:
                st["phases"][ph]["status"] = STALE
        self.save_state(st)

    def first_incomplete(self) -> str | None:
        self.refresh()
        st = self.state()
        for ph in PHASES:
            if st["phases"][ph]["status"] != DONE:
                return ph
        return None

    def is_finished(self) -> bool:
        return self.first_incomplete() is None

    # ---- files -----------------------------------------------------------
    def path(self, rel: str) -> Path:
        return self.root / rel

    def write_raw_source(self, name: str, data: bytes) -> Path:
        """Raw originals are write-once: a second write to the same name is refused."""
        p = self.root / "01-sources" / "raw" / name
        write_bytes_atomic(p, data, overwrite=False)
        return p


def create_run(runs_dir: Path, slug_text: str, *, now: datetime | None = None,
               models: list[str], backend: str, lang: str) -> Run:
    now = now or datetime.now()
    base = f"{now:%Y%m%d-%H%M}-{slugify(slug_text)}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    root = runs_dir / base
    n = 2
    while root.exists():
        root = runs_dir / f"{base}-{n}"
        n += 1
    root.mkdir()
    state = {
        "version": 1,
        "created_at": now.isoformat(timespec="seconds"),
        "models": list(models),
        "backend": backend,
        "lang": lang,
        "phases": {ph: {"status": PENDING} for ph in PHASES},
    }
    write_json(root / "state.json", state)
    return Run(root)


def list_runs(runs_dir: Path) -> list[Run]:
    if not runs_dir.exists():
        return []
    return [Run(p) for p in sorted(runs_dir.iterdir()) if (p / "state.json").is_file()]


def unfinished_runs(runs_dir: Path) -> list[Run]:
    return [r for r in list_runs(runs_dir) if not r.is_finished()]

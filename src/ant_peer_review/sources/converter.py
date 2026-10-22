"""Local file / folder conversion to Markdown.

Refuses symlinks (file or directory) so nothing outside the given folder is
read, reads only allowlisted types, caps size, and checks the input's sha256
did not change while it was being read.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from ..jsonio import sha256_bytes
from .htmlmd import html_to_markdown

SUPPORTED = {".md", ".markdown", ".txt", ".html", ".htm", ".docx", ".pdf"}
MAX_FILE_BYTES = 20_000_000
MAX_DOCX_XML_BYTES = 50_000_000
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ConvertError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class Doc:
    origin: str
    title: str
    markdown: str
    raw: bytes
    hidden: list[dict] = field(default_factory=list)


@dataclass
class Skipped:
    origin: str
    reason: str


def docx_to_markdown(data: bytes) -> str:
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise ConvertError("too_large", f"document.xml {info.file_size} bytes")
            with z.open(info) as f:
                xml = f.read(MAX_DOCX_XML_BYTES + 1)
        if len(xml) > MAX_DOCX_XML_BYTES:  # header lied about the size
            raise ConvertError("too_large", "document.xml")
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, EOFError) as e:
        raise ConvertError("corrupt", str(e)[:200])
    paras = []
    for p in root.iter(f"{W_NS}p"):
        style = p.find(f"{W_NS}pPr/{W_NS}pStyle")
        text = "".join(t.text or "" for t in p.iter(f"{W_NS}t")).strip()
        if not text:
            continue
        sval = style.get(f"{W_NS}val", "") if style is not None else ""
        m = re.match(r"(?i)heading\s*(\d)", sval)
        paras.append(("#" * int(m.group(1)) + " " + text) if m else text)
    return "\n\n".join(paras)


def pdf_to_markdown(path: Path) -> str:
    try:
        from pypdf import PdfReader  # optional extra
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            return "\n\n".join((pg.extract_text() or "").strip() for pg in reader.pages).strip()
        except Exception as e:  # pypdf raises many types on malformed input
            raise ConvertError("corrupt", str(e)[:200])
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                             text=True, timeout=120)
        if out.returncode == 0:
            return out.stdout.strip()
    raise ConvertError("pdf_unsupported", "install the 'pdf' extra (pypdf) or pdftotext")


def convert_file(path: Path, origin: str | None = None) -> Doc:
    path = Path(path)
    origin = origin or str(path)
    if path.is_symlink():
        raise ConvertError("symlink", origin)
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ConvertError("not_regular_file", origin)  # FIFOs/devices would block
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ConvertError("unsupported_type", ext or "(none)")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ConvertError("too_large", str(size))
    raw = path.read_bytes()
    before = sha256_bytes(raw)
    hidden: list[dict] = []
    title = path.stem
    if ext in (".md", ".markdown", ".txt"):
        md = raw.decode("utf-8", "replace")
        # Markdown can hide text in HTML comments; surface them for the scan.
        hidden = [{"kind": "comment", "text": c.strip()}
                  for c in re.findall(r"<!--(.*?)-->", md, re.S) if c.strip()]
        md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    elif ext in (".html", ".htm"):
        conv = html_to_markdown(raw.decode("utf-8", "replace"))
        md, hidden, title = conv.markdown, conv.hidden, conv.title or title
    elif ext == ".docx":
        md = docx_to_markdown(raw)
    else:
        md = pdf_to_markdown(path)
    if sha256_bytes(path.read_bytes()) != before:
        raise ConvertError("changed_during_read", origin)
    return Doc(origin=origin, title=title, markdown=md.strip(), raw=raw, hidden=hidden)


def convert_folder(folder: Path) -> tuple[list[Doc], list[Skipped]]:
    folder = Path(folder)
    if folder.is_symlink():
        return [], [Skipped(str(folder), "symlink")]
    root = folder.resolve()
    docs: list[Doc] = []
    skipped: list[Skipped] = []

    def walk(d: Path):
        for entry in sorted(d.iterdir()):
            rel = str(entry.relative_to(folder))
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                skipped.append(Skipped(rel, "symlink"))
                continue
            if entry.is_dir():
                walk(entry)
                continue
            if not entry.is_file():
                skipped.append(Skipped(rel, "not_regular_file"))
                continue
            if root not in entry.resolve().parents:
                skipped.append(Skipped(rel, "outside_folder"))
                continue
            try:
                docs.append(convert_file(entry, origin=rel))
            except ConvertError as e:
                skipped.append(Skipped(rel, e.reason))

    walk(folder)
    return docs, skipped

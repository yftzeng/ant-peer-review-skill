"""Backend B: `claude -p` subprocess, using the user's Claude Code login.

Isolation: a fresh empty working directory, our own system prompt, no setting
sources (so user hooks/CLAUDE.md never leak into a review), no session saved,
and only the tools a step names.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

from ..schemas import validate
from .base import MODEL_IDS, Backend, BackendError, Result

MAX_ATTEMPTS = 2


class ClaudeCliBackend(Backend):
    name = "claude-cli"

    def __init__(self, executable: str | None = None):
        self.exe = executable or os.environ.get("ANT_PEER_REVIEW_CLAUDE") or "claude"

    def build_cmd(self, model_id: str, system: str, schema: dict,
                  tools: tuple[str, ...], effort: str) -> list[str]:
        cmd = [
            self.exe, "-p",
            "--model", model_id,
            "--system-prompt", system,
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--tools", ",".join(tools) if tools else "",
            "--setting-sources", "",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--effort", effort,
        ]
        if tools:
            cmd += ["--allowedTools", ",".join(tools),
                    "--output-format", "stream-json", "--verbose"]
        else:
            cmd += ["--output-format", "json"]
        return cmd

    def run(self, model, *, task, system, prompt, schema, tools=(), effort="high",
            timeout=900) -> Result:
        if shutil.which(self.exe) is None:
            raise BackendError(f"'{self.exe}' not found on PATH (install Claude Code)",
                               reason="error")
        model_id = MODEL_IDS.get(model, model)
        cmd = self.build_cmd(model_id, system, schema, tuple(tools), effort)
        last_err = ""
        for _ in range(MAX_ATTEMPTS):
            with tempfile.TemporaryDirectory(prefix="apr-call-") as cwd:
                try:
                    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                          cwd=cwd, timeout=timeout)
                except subprocess.TimeoutExpired:
                    raise BackendError(f"{model} timed out after {timeout}s", reason="timeout")
            res = parse_output(proc.stdout, streamed=bool(tools))
            if res is None:
                last_err = (proc.stderr or proc.stdout or "").strip()[-500:]
                if _looks_offline(last_err):
                    raise BackendError(last_err, reason="offline")
                continue
            res.model, res.model_id = model, model_id
            if res.refused:
                return res
            errs = validate(res.data, schema) if res.data is not None else ["no structured_output"]
            if not errs:
                return res
            last_err = "; ".join(errs[:5])
        raise BackendError(f"{model}: no valid output after {MAX_ATTEMPTS} attempts: {last_err}",
                           reason="invalid_output")


def _looks_offline(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ("enotfound", "econnrefused", "network", "getaddrinfo",
                                "connection error", "fetch failed"))


def parse_output(stdout: str, *, streamed: bool) -> Result | None:
    """Turn `claude -p` output into a Result. None if there is no result record."""
    final = None
    calls: list[dict] = []
    results: list[str] = []
    lines = stdout.splitlines() if streamed else [stdout]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = rec.get("type")
        if typ == "assistant":
            for c in rec.get("message", {}).get("content", []):
                if c.get("type") == "tool_use" and c.get("name") != "StructuredOutput":
                    calls.append({"name": c.get("name"), "input": c.get("input")})
        elif typ == "user":
            content = rec.get("message", {}).get("content", [])
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        results.append(_flatten(c.get("content")))
            tur = rec.get("tool_use_result")
            if isinstance(tur, (dict, list)):
                results.append(json.dumps(tur, ensure_ascii=False))
        elif typ == "result":
            final = rec
    if final is None:
        return None
    refused = final.get("stop_reason") == "refusal" or bool(final.get("safety_stops"))
    data = final.get("structured_output")
    if final.get("is_error") and not refused:
        return None
    return Result(model="", model_id="", data=None if refused else data, refused=refused,
                  refusal_detail=str(final.get("result", ""))[:300] if refused else "",
                  cost_usd=final.get("total_cost_usd"), tool_calls=calls,
                  tool_results=results, raw=final)


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_flatten(c.get("text", c) if isinstance(c, dict) else c) for c in content)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)

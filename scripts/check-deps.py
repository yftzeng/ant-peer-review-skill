#!/usr/bin/env python3
"""Dependency audit: the runtime must stay stdlib-only (optional extras allowed).

Exit 0 when [project].dependencies is empty, 1 otherwise. Usage: check-deps.py [pyproject]
"""
import sys
import tomllib

path = sys.argv[1] if len(sys.argv) > 1 else "pyproject.toml"
with open(path, "rb") as f:
    deps = tomllib.load(f).get("project", {}).get("dependencies", [])
if deps:
    print(f"check-deps: FAIL runtime dependencies are not allowed: {deps}")
    sys.exit(1)
print("check-deps: OK (no runtime dependencies)")

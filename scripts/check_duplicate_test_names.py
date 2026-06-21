#!/usr/bin/env python3
"""Fail when one Python test file defines the same test function twice."""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path


def iter_python_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.rglob("test_*.py")))
        elif path.suffix == ".py":
            files.append(path)
    return files


def duplicate_tests(path: Path) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    seen: dict[str, list[int]] = defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            seen[node.name].append(node.lineno)
    return {name: lines for name, lines in seen.items() if len(lines) > 1}


def main(argv: list[str]) -> int:
    paths = argv or ["src/backend/tests", "src/bot/tests"]
    failures: list[str] = []
    for path in iter_python_files(paths):
        for name, lines in duplicate_tests(path).items():
            joined_lines = ", ".join(str(line) for line in lines)
            failures.append(f"{path}:{joined_lines}: duplicate test function {name}")

    if failures:
        print("Duplicate same-file pytest test names found:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

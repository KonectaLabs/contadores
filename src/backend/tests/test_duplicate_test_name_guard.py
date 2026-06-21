from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
GUARD = ROOT_DIR / "scripts" / "check_duplicate_test_names.py"


def run_guard(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *(str(path) for path in paths)],
        check=False,
        text=True,
        capture_output=True,
    )


def test_duplicate_test_name_guard_fails_same_file_duplicate(tmp_path: Path) -> None:
    test_file = tmp_path / "test_shadowed.py"
    test_file.write_text(
        "def test_same():\n    pass\n\n"
        "def test_same():\n    pass\n",
        encoding="utf-8",
    )

    result = run_guard(test_file)

    assert result.returncode == 1
    assert "duplicate test function test_same" in result.stderr


def test_duplicate_test_name_guard_allows_same_name_in_different_files(tmp_path: Path) -> None:
    first = tmp_path / "test_first.py"
    second = tmp_path / "test_second.py"
    first.write_text("def test_same():\n    pass\n", encoding="utf-8")
    second.write_text("def test_same():\n    pass\n", encoding="utf-8")

    result = run_guard(tmp_path)

    assert result.returncode == 0

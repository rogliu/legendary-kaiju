"""Tests for scripts/block-danger-zones.sh.

The script reads a Claude Code PreToolUse hook payload on stdin
(a JSON object with `tool_input.file_path`). It exits 0 if the path
is safe, exits 2 with a message on stderr if the path is a rail file.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "block-danger-zones.sh"


def _invoke(file_path: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": file_path},
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hook_blocks_risk_dir() -> None:
    result = _invoke("kaiju/risk/limits.py")
    assert result.returncode == 2, result.stderr
    assert "rail file" in result.stderr.lower()


import pytest


@pytest.mark.parametrize(
    "rail_path",
    [
        "kaiju/eval/gate.py",
        "kaiju/config.py",
        "kaiju/markets/parser.py",
        "docs/INVARIANTS.md",
        "docs/agents/LOOP.md",
        "AGENTS.md",
        "tests/test_scope_lock.py",
    ],
)
def test_hook_blocks_rail_file(rail_path: str) -> None:
    result = _invoke(rail_path)
    assert result.returncode == 2, result.stderr
    assert "rail file" in result.stderr.lower()


def test_hook_allows_non_rail_file() -> None:
    result = _invoke("kaiju/types.py")
    assert result.returncode == 0, result.stderr


def test_hook_allows_empty_path() -> None:
    """A tool call without a file path (e.g., Bash) is allowed."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_hook_blocks_absolute_path_to_rail() -> None:
    """Edit calls use absolute paths; hook must canonicalize and still block."""
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = _invoke(f"{repo_root}/kaiju/risk/limits.py")
    assert result.returncode == 2, result.stderr

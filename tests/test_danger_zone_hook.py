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

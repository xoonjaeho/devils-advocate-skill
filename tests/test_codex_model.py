"""Tests for scripts/advocate.py's `codex-model` subcommand."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "advocate.py"


def run_codex_model(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "codex-model"],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "CODEX_HOME": str(tmp_path)},
    )


def test_top_level_model_ignores_related_keys_and_profile(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        'model_reasoning_effort = "high"\n'
        'model = "gpt-x"\n'
        "[profiles.p]\n"
        'model = "other"\n',
        encoding="utf-8",
    )

    result = run_codex_model(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "gpt-x\n"
    assert result.stderr == ""


def test_profile_model_is_not_a_top_level_model(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[profiles.p]\n"
        'model = "other"\n',
        encoding="utf-8",
    )

    result = run_codex_model(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "codex-default\n"
    assert result.stderr == ""


def test_top_level_profile_means_codex_default(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        'model = "gpt-x"\n'
        'profile = "p"\n'
        "[profiles.p]\n"
        'model = "other"\n',
        encoding="utf-8",
    )

    result = run_codex_model(tmp_path)

    assert result.stdout == "codex-default\n"


def test_non_utf8_config_falls_back_to_codex_default(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_bytes(b'model = "gpt-x"\n# \xff\xfe\n')

    result = run_codex_model(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "codex-default\n"
    assert result.stderr == ""


def test_missing_config_falls_back_to_codex_default(tmp_path: Path) -> None:
    result = run_codex_model(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "codex-default\n"
    assert result.stderr == ""


def test_single_quoted_model_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("model = 'gpt-y'\n", encoding="utf-8")

    result = run_codex_model(tmp_path)

    assert result.returncode == 0
    assert result.stdout == "gpt-y\n"


@pytest.mark.skipif(tomllib is None, reason="needs tomllib (Python 3.11+)")
def test_toml_escape_in_model_is_decoded(tmp_path):
    (tmp_path / "config.toml").write_text('model = "gpt-\\u0078"\n', encoding="utf-8")

    result = run_codex_model(tmp_path)

    assert result.stdout.strip() == "gpt-x"

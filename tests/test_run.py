"""Tests for scripts/advocate.py's `run` subcommand, driven by fake `codex` / `claude` executables."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "advocate.py"
DOC = "# canned review\n"

FAKE_ENGINE = r'''
import json, os, sys, time

argv = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
if argv[:2] == ["login", "status"]:
    if mode == "login_sleep":
        time.sleep(30)
    if mode == "login_orphan":
        import subprocess
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        time.sleep(30)
    sys.exit(1 if mode == "login_fail" else 0)
stdin = sys.stdin.buffer.read()
with open(os.environ["FAKE_LOG"], "w", encoding="utf-8") as f:
    json.dump({"argv": argv, "stdin": stdin.decode("utf-8")}, f)
if mode == "sleep":
    time.sleep(30)
if mode == "fail":
    sys.stderr.write("boom\n")
    sys.exit(7)
doc = "" if mode == "empty" else os.environ["FAKE_DOC"]
if "-o" in argv:
    open(argv[argv.index("-o") + 1], "w", encoding="utf-8").write(doc)
else:
    sys.stdout.write(doc)
if mode == "noisy":
    sys.stdout.write("x" * 5_000_000)
'''


def install_fake(bin_dir: Path, name: str) -> None:
    script = bin_dir / "fake_engine.py"
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / f"{name}.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        wrapper = bin_dir / name
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def env(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    install_fake(bin_dir, "codex")
    install_fake(bin_dir, "claude")
    codex_home = tmp_path / "codexhome"
    codex_home.mkdir()
    return {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "CODEX_HOME": str(codex_home),
        "FAKE_LOG": str(tmp_path / "log.json"),
        "FAKE_DOC": DOC,
        "PYTHONUTF8": "1",
    }


@pytest.fixture
def packet(tmp_path: Path) -> Path:
    path = tmp_path / "packet.md"
    path.write_bytes("packet 한글\n".encode("utf-8"))
    return path


def run(tmp_path: Path, env: dict, packet: Path, engine: str, *extra: str):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    out = tmp_path / "out.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--engine", engine, "--repo", str(repo),
         "--packet", str(packet), "--out", str(out), *extra],
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    return result, out, repo


def logged(env: dict) -> dict:
    return json.loads(Path(env["FAKE_LOG"]).read_text(encoding="utf-8"))


def test_codex_static_argv_and_stdin(tmp_path, env, packet):
    result, out, repo = run(tmp_path, env, packet, "codex")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "expect: codex-default\n"
    assert out.read_text(encoding="utf-8") == DOC
    log = logged(env)
    argv = log["argv"]
    assert argv[:7] == ["exec", "-s", "read-only", "-C", str(repo.resolve()), "-c", "model_reasoning_effort=high"]
    assert argv[7] == "-o" and argv[9] == "-" and len(argv) == 10
    assert Path(argv[8]).parent == out.resolve().parent and Path(argv[8]) != out.resolve()
    assert log["stdin"] == "packet 한글\n"


def test_codex_test_method_uses_workspace_write_and_never_passes_model(tmp_path, env, packet):
    Path(env["CODEX_HOME"], "config.toml").write_text("model = 'gpt-x'\n", encoding="utf-8")

    result, out, repo = run(tmp_path, env, packet, "codex", "--method", "TEST")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "expect: gpt-x\n"
    argv = logged(env)["argv"]
    assert argv[:7] == [
        "exec", "-s", "workspace-write", "-C", str(repo.resolve()),
        "-c", "model_reasoning_effort=high",
    ]
    assert argv[7] == "-o" and argv[9] == "-" and len(argv) == 10
    assert "-m" not in argv


def test_claude_argv_has_read_only_git_and_allow_pattern(tmp_path, env, packet):
    allow = "Bash(python -m pytest *)"

    result, out, _ = run(tmp_path, env, packet, "claude", "--allow", allow)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "expect: claude-opus\n"
    assert out.read_text(encoding="utf-8") == DOC
    log = logged(env)
    argv = log["argv"]
    assert argv[:5] == ["-p", "--model", "opus", "--permission-mode", "dontAsk"]
    assert argv[5:7] == ["--tools", "Read,Grep,Glob,Bash"]
    assert argv[7] == "--strict-mcp-config"
    assert argv[8:12] == [
        "--disallowedTools", "Bash(git *--out*)", "Bash(git *--ext-diff*)", "Bash(git *--textconv*)",
    ]
    assert argv[12] == "--allowedTools"
    assert "--mcp-config" not in argv
    tools = argv[13]
    assert "Bash(git *)" not in tools
    assert "Bash(git grep *)" not in tools
    assert "Bash(git diff *)" in tools and "Bash(git blame *)" in tools
    assert tools.split(" ", 2)[:2] == ["Read", "Grep"]
    assert tools.endswith(allow)
    assert len(argv) == 14
    assert log["stdin"] == "packet 한글\n"


def test_missing_cli_exits_3(tmp_path, env, packet):
    empty = tmp_path / "empty"
    empty.mkdir()

    result, _, _ = run(tmp_path, {**env, "PATH": str(empty)}, packet, "claude")

    assert result.returncode == 3
    assert result.stderr.strip() == "engine unavailable: claude not on PATH"
    assert result.stdout == ""


def test_codex_login_failure_exits_3(tmp_path, env, packet):
    result, _, _ = run(tmp_path, {**env, "FAKE_MODE": "login_fail"}, packet, "codex")

    assert result.returncode == 3
    assert result.stderr.strip() == "engine unavailable: codex not logged in"


def test_timeout_exits_4(tmp_path, env, packet):
    result, _, _ = run(tmp_path, {**env, "FAKE_MODE": "sleep"}, packet, "claude", "--timeout", "2")

    assert result.returncode == 4
    assert result.stderr.strip() == "engine timeout after 2 s"


def test_engine_failure_exits_5_with_stderr_tail(tmp_path, env, packet):
    result, _, _ = run(tmp_path, {**env, "FAKE_MODE": "fail"}, packet, "codex")

    assert result.returncode == 5
    assert "engine failed: exit 7" in result.stderr
    assert "boom" in result.stderr


@pytest.mark.parametrize("engine", ["codex", "claude"])
def test_empty_output_exits_6(tmp_path, env, packet, engine):
    result, _, _ = run(tmp_path, {**env, "FAKE_MODE": "empty"}, packet, engine)

    assert result.returncode == 6
    assert result.stderr.strip() == "engine produced no output"
    assert result.stdout == ""


def test_missing_packet_keeps_existing_out(tmp_path, env):
    out = tmp_path / "out.md"
    out.write_text("old\n", encoding="utf-8")

    result, _, _ = run(tmp_path, env, tmp_path / "nope.md", "claude")

    assert result.returncode == 2
    assert "cannot read packet" in result.stderr
    assert out.read_text(encoding="utf-8") == "old\n"


@pytest.mark.parametrize("mode,code", [("fail", 5), ("empty", 6)])
@pytest.mark.parametrize("engine", ["codex", "claude"])
def test_engine_failure_keeps_existing_out_and_leaves_no_temp(tmp_path, env, packet, engine, mode, code):
    out = tmp_path / "out.md"
    out.write_text("old\n", encoding="utf-8")

    result, _, _ = run(tmp_path, {**env, "FAKE_MODE": mode}, packet, engine)

    assert result.returncode == code
    assert out.read_text(encoding="utf-8") == "old\n"
    assert sorted(p.name for p in tmp_path.glob(".out.md.*")) == []


def test_out_equal_to_packet_rejected(tmp_path, env, packet):
    repo = tmp_path / "repo"
    repo.mkdir()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--engine", "claude", "--repo", str(repo),
         "--packet", str(packet), "--out", str(packet)],
        capture_output=True, encoding="utf-8", env=env,
    )

    assert result.returncode == 2
    assert "same file" in result.stderr
    assert packet.read_bytes() == "packet 한글\n".encode("utf-8")


def test_codex_login_status_timeout_exits_3(tmp_path, env, packet):
    shim = tmp_path / "shim.py"
    shim.write_text(
        "import sys\n"
        "sys.path.insert(0, sys.argv.pop(1))\n"
        "import advocate\n"
        "advocate.LOGIN_TIMEOUT = 1\n"
        "sys.argv[0] = 'advocate.py'\n"
        "sys.exit(advocate.main())\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    result = subprocess.run(
        [sys.executable, str(shim), str(SCRIPT.parent), "run", "--engine", "codex", "--repo", str(repo),
         "--packet", str(packet), "--out", str(tmp_path / "out.md")],
        capture_output=True, encoding="utf-8", env={**env, "FAKE_MODE": "login_sleep"},
    )

    assert result.returncode == 3
    assert result.stderr.strip() == "engine unavailable: codex login status timed out"


@pytest.mark.parametrize("value", ["0", "-5"])
def test_nonpositive_timeout_rejected(tmp_path, env, packet, value):
    result, _, _ = run(tmp_path, env, packet, "claude", "--timeout", value)

    assert result.returncode == 2
    assert "must be > 0" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe shims are Windows-only")
def test_cmd_shim_refuses_metacharacters_in_repo_path(tmp_path, env, packet):
    repo = tmp_path / "a&b"
    repo.mkdir()
    out = tmp_path / "out.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--engine", "claude", "--repo", str(repo),
         "--packet", str(packet), "--out", str(out)],
        capture_output=True, encoding="utf-8", env=env,
    )

    assert result.returncode == 3
    assert "--repo" in result.stderr and "&" in result.stderr
    assert not out.exists()
    assert not Path(env["FAKE_LOG"]).exists()


def test_codex_stdout_is_not_captured_or_printed(tmp_path, env, packet):
    result, out, _ = run(tmp_path, {**env, "FAKE_MODE": "noisy"}, packet, "codex")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "expect: codex-default\n"
    assert out.read_text(encoding="utf-8") == DOC


def test_login_check_is_bounded_when_a_grandchild_holds_the_pipes(tmp_path, env, packet):
    shim = tmp_path / "shim.py"
    shim.write_text(
        "import sys\n"
        "sys.path.insert(0, sys.argv.pop(1))\n"
        "import advocate\n"
        "advocate.LOGIN_TIMEOUT = 1\n"
        "sys.argv[0] = 'advocate.py'\n"
        "sys.exit(advocate.main())\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(shim), str(SCRIPT.parent), "run", "--engine", "codex", "--repo", str(repo),
         "--packet", str(packet), "--out", str(tmp_path / "out.md")],
        capture_output=True, encoding="utf-8", env={**env, "FAKE_MODE": "login_orphan"},
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 3
    assert result.stderr.strip() == "engine unavailable: codex login status timed out"
    assert elapsed < 15


def test_unlink_failure_keeps_exit_code_and_reports_tmp(tmp_path, env, packet, monkeypatch, capsys):
    sys.path.insert(0, str(SCRIPT.parent))
    import advocate

    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setenv("FAKE_MODE", "fail")
    monkeypatch.setenv("FAKE_LOG", env["FAKE_LOG"])
    monkeypatch.setenv("PYTHONUTF8", "1")
    real_unlink = Path.unlink

    def locked(self, missing_ok=False):
        if self.suffix == ".tmp":
            raise PermissionError("sharing violation")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    repo = tmp_path / "repo"
    repo.mkdir()
    args = advocate.argparse.Namespace(
        engine="claude", repo=str(repo), packet=str(packet), out=str(tmp_path / "out.md"),
        method="STATIC", allow=[], timeout=30,
    )

    code = advocate.cmd_run(args)

    assert code == 5
    assert "left behind" in capsys.readouterr().err

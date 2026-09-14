"""Tests for scripts/advocate.py's `check` and `build` subcommands."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "advocate.py"
EXPECT = "claude-opus-5"

BASE_FIXTURE = """# 😈 Devil's Advocate Review — advocate.py build/check implementation

Reviewer: claude-opus-5
Self-identified: claude-opus-5
Target: scripts/advocate.py   Base: abc1234   Date: 2026-09-14 15:00
Scope: scripts/advocate.py reviewed; tests/test_check.py skipped (generated)   Focus: none
Method: STATIC   Kind: script   Lang: en

## 📋 Overview
- What it does: Parses a devil's advocate review document against a frozen template and validates its structure.
- Verdict: 🔧 FIX FIRST — F1 is a Major finding with High confidence.
- Counts: 🔴 Blocker 0 · 🟠 Major 1 · 🟡 Minor 0 · 🟢 Nit 1 · 💡 Alternatives 1 · ❓ Questions 1
- What held: 🛡️ malformed placeholder detection and counts recomputation both resisted tampering.

## 🧪 Stress log
| # | Scenario | Result | How checked |
|---|----------|--------|-------------|
| S1 | empty input file | 🛡️ held | STATIC: scripts/advocate.py:120 |
| S2 | crash mid-write leaves partial output | 💥 broke → F1 | STATIC: scripts/advocate.py:145 |
| S3 | auth/tenant boundary | ➖ n/a: single-user CLI script, no auth boundary | — |
| S4 | unused CLI flag | 💥 broke → F2 | STATIC: scripts/advocate.py:200 |
| S5 | resource limits | ➖ n/a: bounded by --max-bytes, no unbounded loop | — |

## 🔍 Findings
### F1 · 🟠 Major · confidence High · build does not flush output on error path
- Where: `scripts/advocate.py:145`
- Claim: if write fails partway, no cleanup of the partial output file happens.
- Evidence: the `with open(out_path, "w", ...)` block has no error handling around `f.write(packet)`.
- Impact: a caller could see a truncated packet file and mistake it for a complete one.
- Fix: extract a module-level constant.

### F2 · 🟢 Nit · confidence Low · unused --max-bytes default could be a constant
- Where: `scripts/advocate.py:200`
- Claim: the literal 400000 default is repeated in the help text and the code.
- Evidence: `default=400000` appears without a named constant.
- Impact: none functionally; a future edit could let the two drift.
- Fix: extract a module-level constant.

## 💡 Better alternatives
### A1 · replaces F1 · write via a temp file and atomic rename
- Current: `build` opens OUT directly and writes the packet in place.
- Proposed: write to `OUT.tmp` then `os.replace(OUT.tmp, OUT)`.
- Better on: correctness — a crash mid-write can no longer leave a truncated packet at OUT.
- Costs: one extra rename syscall; negligible.
- Evidence: this is the standard atomic-write pattern used elsewhere in the repo's ollama plugin.

## ❓ Questions to the author
- Q1 (re F1): is a truncated packet file ever consumed automatically downstream, or always inspected by a human first? — a human-only consumer would lower F1 to Minor.

## 👍 Held up
- Placeholder detection correctly ignores fenced code and inline backticks (`scripts/advocate.py:210`).
- Counts and Verdict are recomputed from the F# headings rather than trusted from the document, closing the main tamper path.

## ⚠️ Not verified
- LIVE behavior against a real ollama-authored review was not exercised; only STATIC reads of the script.
"""


def write_fixture(tmp_path: Path, content: str, name: str = "review.md") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def run_check(path: Path, expect: str = EXPECT, stamp: bool = False):
    cmd = [sys.executable, str(SCRIPT), "check", str(path), "--expect", expect]
    if stamp:
        cmd.append("--stamp")
    return subprocess.run(cmd, capture_output=True, encoding="utf-8")


def test_base_fixture_passes(tmp_path):
    path = write_fixture(tmp_path, BASE_FIXTURE)
    result = run_check(path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_leftover_placeholder_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "- Fix: extract a module-level constant.\n\n## 💡",
        "- Fix: <left as an exercise>\n\n## 💡",
        1,
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: placeholder" in result.stdout


def test_html_entity_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "Impact: a caller could see a truncated packet file and mistake it for a complete one.",
        "Impact: a caller could see a &lt;truncated&gt; packet file and mistake it for a complete one.",
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: entity" in result.stdout


def test_counts_mismatch_fails(tmp_path):
    content = BASE_FIXTURE.replace("🟠 Major 1 ·", "🟠 Major 2 ·")
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: counts" in result.stdout


def test_reviewer_mismatch_fails(tmp_path):
    content = BASE_FIXTURE.replace("Reviewer: claude-opus-5\n", "Reviewer: gpt-6-astra\n")
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: reviewer" in result.stdout


def test_missing_evidence_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        '- Evidence: the `with open(out_path, "w", ...)` block has no error handling around `f.write(packet)`.',
        "- Evidence:",
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: finding" in result.stdout


def test_test_row_under_static_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "STATIC: scripts/advocate.py:120", "TEST: scripts/advocate.py:120"
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: method" in result.stdout


def test_fewer_than_three_nonna_rows_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "| S4 | unused CLI flag | 💥 broke → F2 | STATIC: scripts/advocate.py:200 |",
        "| S4 | unused CLI flag | ➖ n/a: not applicable | — |",
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: stress" in result.stdout


def test_translated_heading_fails(tmp_path):
    content = BASE_FIXTURE.replace("## 👍 Held up", "## 👍 잘한 점")
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: headings" in result.stdout


def test_translated_level_word_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "### F1 · 🟠 Major · confidence High ·", "### F1 · 🟠 주요 · confidence High ·"
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: finding" in result.stdout


def test_no_alternative_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "### A1 · replaces F1 · write via a temp file and atomic rename\n", ""
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: alternatives" in result.stdout


def test_verdict_mismatch_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "- Verdict: 🔧 FIX FIRST — F1 is a Major finding with High confidence.",
        "- Verdict: ✅ SHIP — F1 is a Major finding with High confidence.",
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: verdict" in result.stdout


def test_preamble_fails(tmp_path):
    content = BASE_FIXTURE.replace(
        "# 😈 Devil's Advocate Review", "Some prose before the heading.\n# 😈 Devil's Advocate Review", 1
    )
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 1
    assert "FAIL: preamble" in result.stdout


def test_self_identified_mismatch_only_warns(tmp_path):
    content = BASE_FIXTURE.replace("Self-identified: claude-opus-5", "Self-identified: gpt-6-astra")
    path = write_fixture(tmp_path, content)
    result = run_check(path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WARN: reviewer" in result.stdout


def test_stamp_inserts_reviewer_line(tmp_path):
    content = BASE_FIXTURE.replace("Reviewer: claude-opus-5\n", "")
    path = write_fixture(tmp_path, content)
    result = run_check(path, stamp=True)
    assert result.returncode == 0, result.stdout + result.stderr
    written = path.read_text(encoding="utf-8")
    assert "Reviewer: claude-opus-5\nSelf-identified:" in written


def test_build_fences_diff_and_prefills_header(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *cmd: subprocess.run(cmd, cwd=repo, capture_output=True, encoding="utf-8", check=True)
    run("git", "init")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test")
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    run("git", "add", "hello.txt")
    run("git", "commit", "-m", "init")
    (repo / "hello.txt").write_text("hello world\n", encoding="utf-8")
    run("git", "add", "hello.txt")
    run("git", "commit", "-m", "update")

    out_path = repo / "packet.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "build", "HEAD", "-o", str(out_path), "--kind", "cli", "--lang", "en"],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    packet = out_path.read_text(encoding="utf-8")
    assert "```diff" in packet
    assert "Kind: cli" in packet
    assert "Lang: en" in packet
    assert not re.search(r"(?m)^Reviewer:", packet), "template's Reviewer: header line must be stripped"
    assert "## Output template" in packet


def test_build_rejects_oversized_packet(tmp_path):
    target = tmp_path / "small.txt"
    target.write_text("hello\n", encoding="utf-8")
    out_path = tmp_path / "packet.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "build", str(target), "-o", str(out_path), "--max-bytes", "10"],
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    assert not out_path.exists()


def test_evidence_quote_on_next_line_passes(tmp_path):
    # regression: a fenced quote starting on the line after "- Evidence:" is evidence, not empty
    content = BASE_FIXTURE.replace("- Evidence: ", "- Evidence:\n  ```\n  ", 1)
    content = content.replace("\n- Impact:", "\n  ```\n- Impact:", 1)
    result = run_check(write_fixture(tmp_path, content))
    assert result.returncode == 0, result.stdout

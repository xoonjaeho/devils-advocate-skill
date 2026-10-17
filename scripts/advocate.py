"""Build devil's advocate review packets and check finished reviews against TEMPLATE.md."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".venv"}
LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
}
MAX_NITS = 3
EXPECTED_HEADINGS = [
    "Overview",
    "Stress log",
    "Findings",
    "Better alternatives",
    "Questions to the author",
    "Held up",
    "Not verified",
]
FINDING_HEADING_RE = re.compile(
    r"^### F(?P<num>\d+) · \S+ (?P<level>Blocker|Major|Minor|Nit) "
    r"· confidence (?P<conf>High|Medium|Low) · (?P<title>.+)$"
)
WHERE_LOC_RE = re.compile(r"`\S+:\d+`")
PLACEHOLDER_RE = re.compile(r"<[^<>\n]+>")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
ENTITY_RE = re.compile(r"&lt;|&gt;|&amp;")
ALT_BULLETS = ["Current:", "Proposed:", "Better on:", "Costs:", "Evidence:"]
FINDING_BULLETS = ["Where:", "Claim:", "Evidence:", "Impact:", "Fix:"]
COUNT_LABEL_RE = {
    "Blocker": re.compile(r"Blocker\s+(\d+)"),
    "Major": re.compile(r"Major\s+(\d+)"),
    "Minor": re.compile(r"Minor\s+(\d+)"),
    "Nit": re.compile(r"Nit\s+(\d+)"),
    "Alternatives": re.compile(r"Alternatives\s+(\d+)"),
    "Questions": re.compile(r"Questions\s+(\d+)"),
}


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def is_binary(path: Path) -> bool:
    with path.open("rb") as f:
        chunk = f.read(4096)
    return b"\x00" in chunk


def fence(text: str, lang: str) -> str:
    """Fence `text` with one more backtick than its longest backtick run (min 3)."""
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{text}\n{ticks}\n"


def fence_file(path: Path, heading: str) -> str:
    lang = path.suffix.lstrip(".")
    text = path.read_text(encoding="utf-8", errors="replace")
    return f"### {heading}\n{fence(text, lang)}"


def walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def git_lines(args: list[str], cwd: Path | None = None) -> list[str] | None:
    """Stdout lines of a git command, or None when git is missing or the command fails."""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args], capture_output=True, text=True, encoding="utf-8", cwd=cwd
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return [l for l in proc.stdout.split("\n") if l]


def list_dir_files(root: Path) -> tuple[list[Path], list[str]]:
    """Files to review under `root` and the skip notes (reason: what) for the Target section."""
    ls = ["ls-files", "-co", "--exclude-standard", "--", "."]
    inside = git_lines(["rev-parse", "--is-inside-work-tree"], cwd=root)
    listed = git_lines(ls, cwd=root) if inside else None
    if listed is not None:
        names = sorted(listed)
        ignored = git_lines(["ls-files", "-o", "-i", "--exclude-standard", "--", "."], cwd=root) or []
    else:
        names = [p.relative_to(root).as_posix() for p in walk_files(root)]
        ignored = []
    files, notes = [], []
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        if path.name in LOCKFILES:
            notes.append(f"lockfile: {name}")
        else:
            files.append(path)
    if ignored:
        notes.append(f".gitignore: {len(ignored)} file(s)")
    return files, notes


def build_target_section(target_path: Path) -> str:
    parts = []
    notes: list[str] = []
    if target_path.is_dir():
        files, notes = list_dir_files(target_path)
        if notes and not files:
            sys.stderr.write(
                f"everything under {target_path} was excluded ({'; '.join(notes)}); pass the file explicitly\n"
            )
            sys.exit(1)
        for file_path in files:
            if is_binary(file_path):
                continue
            rel = file_path.relative_to(target_path).as_posix()
            parts.append(fence_file(file_path, rel))
    else:
        parts.append(fence_file(target_path, str(target_path)))
    return "## Target\n\n" + skipped_block(notes) + "\n".join(parts)


def skipped_block(notes: list[str]) -> str:
    if not notes:
        return ""
    return "Skipped by default exclusions:\n" + "".join(f"- {n}\n" for n in notes) + "\n"


def lockfile_excludes() -> list[str]:
    return [f":(exclude,top,glob)**/{name}" for name in sorted(LOCKFILES)]


def diff_args(target: str | None) -> list[str]:
    """`git diff` arguments (without pathspec) for a rev, a range, or the working tree (None)."""
    if target is None:
        return ["diff", "HEAD"]
    return ["diff", target] if ".." in target else ["diff", f"{target}~1", target]


def run_git_diff(base_args: list[str], label: str) -> tuple[str, list[str]]:
    """Diff with lockfiles excluded; returns (diff text, skip notes). Exits 1 on git error or nothing to review."""
    proc = subprocess.run(
        ["git", *base_args, "--", ":(top)", *lockfile_excludes()], capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(1)
    if proc.stdout:
        return proc.stdout, diff_skip_notes(base_args)
    notes = diff_skip_notes(base_args)
    if notes:
        sys.stderr.write(f"diff for {label} touches only excluded files ({'; '.join(notes)}); pass the file explicitly\n")
    else:
        sys.stderr.write(f"empty diff for {label}\n")
    sys.exit(1)


def diff_skip_notes(base_args: list[str]) -> list[str]:
    names = git_lines([*base_args, "--name-only", "--", ":(top)"]) or []
    return [f"lockfile: {n}" for n in names if n.rsplit("/", 1)[-1] in LOCKFILES]


def get_base_sha() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        return "n/a"
    return proc.stdout.strip()


def fill_template(text: str, target: str, base_sha: str, date_str: str, focus: str, method: str, kind: str, lang: str) -> str:
    text = re.sub(r"(?m)^Reviewer:.*\n", lambda m: "", text, count=1)
    text = re.sub(
        r"(?m)^Target: .*$",
        lambda m: f"Target: {target}   Base: {base_sha}   Date: {date_str}",
        text,
        count=1,
    )
    text = re.sub(r"Focus: <[^<>\n]*>", lambda m: f"Focus: {focus}", text, count=1)
    text = re.sub(
        r"(?m)^Method: .*$",
        lambda m: f"Method: {method}   Kind: {kind}   Lang: {lang}",
        text,
        count=1,
    )
    return text


def cmd_build(args: argparse.Namespace) -> int:
    """Assemble one packet file from packet.md + the target + the pre-filled template."""
    root = Path(__file__).resolve().parent.parent
    packet_text = (root / "packet.md").read_text(encoding="utf-8")
    template_text = (root / "TEMPLATE.md").read_text(encoding="utf-8")

    target_label = args.target
    if args.target is not None and Path(args.target).exists():
        target_section = build_target_section(Path(args.target))
    else:
        if args.target is None:
            target_label = "working tree"
            clean = subprocess.run(
                ["git", "diff", "HEAD", "--quiet", "--", ":(top)", *lockfile_excludes()], capture_output=True
            )
            lock_only = (
                clean.returncode == 0
                and subprocess.run(["git", "diff", "HEAD", "--quiet", "--", ":(top)"], capture_output=True).returncode
                == 1
            )
            if clean.returncode == 0 and not lock_only:
                target_label = "working tree (clean; reviewing HEAD)"
                base_args = diff_args("HEAD")
            else:
                # A lockfile-only change reaches run_git_diff as an empty diff with skip notes and exits 1 there.
                base_args = diff_args(None)
        else:
            base_args = diff_args(args.target)
        diff_text, notes = run_git_diff(base_args, target_label)
        target_section = f"## Target\n\n{skipped_block(notes)}{fence(diff_text, 'diff')}"

    base_sha = get_base_sha()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    focus = args.focus if args.focus else "none"
    filled_template = fill_template(
        template_text, target_label, base_sha, date_str, focus, args.method, args.kind, args.lang
    )

    packet = (
        packet_text.rstrip("\n")
        + "\n\n"
        + target_section.rstrip("\n")
        + "\n\n"
        + "## Output template — copy literally, fill every <…>\n\n"
        + filled_template
    )

    size = len(packet.encode("utf-8"))
    if size > args.max_bytes:
        print(f"packet too large: {size} bytes > {args.max_bytes}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(packet)
    return 0


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def strip_glyph(text: str) -> str:
    return re.sub(r"^[\W]+", "", text.strip(), flags=re.UNICODE).strip()


def compute_in_fence(lines: list[str]) -> list[bool]:
    """True for each line inside (or opening/closing) a ``` fence."""
    flags = []
    state = False
    for line in lines:
        if line.strip().startswith("```"):
            state = not state
            flags.append(True)
        else:
            flags.append(state)
    return flags


def visible(lines: list[str]) -> list[str]:
    """`lines` with fenced content blanked out, for scans over structural markers."""
    return ["" if in_fence else line for line, in_fence in zip(lines, compute_in_fence(lines))]


def extract_section(lines: list[str], name: str) -> list[str]:
    vis = visible(lines)
    start = None
    for i, line in enumerate(vis):
        if line.startswith("## ") and strip_glyph(line[3:]) == name:
            start = i + 1
            break
    if start is None:
        return []
    end = start
    while end < len(vis) and not vis[end].startswith("## "):
        end += 1
    return lines[start:end]


def check_preamble(lines: list[str]) -> list[tuple[str, str]]:
    errors = []
    first = next((l for l in lines if l.strip()), "")
    if not (first.startswith("# ") and "Devil's Advocate Review" in first):
        errors.append(("preamble", f"first non-blank line is not a valid H1: {first!r}"))
    if first.strip().startswith("```"):
        errors.append(("preamble", "document starts with a code fence"))
    return errors


def check_headings(lines: list[str]) -> list[tuple[str, str]]:
    found = [strip_glyph(l[3:]) for l in visible(lines) if l.startswith("## ")]
    if found != EXPECTED_HEADINGS:
        return [("headings", f"expected {EXPECTED_HEADINGS}, found {found}")]
    return []


def check_header(lines: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    errors = []
    heading_idx = next((i for i, l in enumerate(visible(lines)) if l.startswith("## ")), len(lines))
    header_lines = lines[:heading_idx]
    header_text = "\n".join(header_lines)
    for prefix in ("Reviewer:", "Self-identified:", "Target:", "Scope:", "Method:"):
        if not any(l.startswith(prefix) for l in header_lines):
            errors.append(("header", f"missing {prefix} line"))
    m = re.search(r"Method:\s*(\S+)", header_text)
    if m and m.group(1) not in {"STATIC", "TEST", "LIVE"}:
        errors.append(("header", f"invalid Method value: {m.group(1)}"))
    m = re.search(r"Kind:\s*(\S+)", header_text)
    if m and m.group(1) not in {"service", "cli", "script", "doc"}:
        errors.append(("header", f"invalid Kind value: {m.group(1)}"))
    m = re.search(r"Lang:\s*(\S+)", header_text)
    if m and m.group(1) not in {"ko", "en"}:
        errors.append(("header", f"invalid Lang value: {m.group(1)}"))
    return errors, header_lines


def check_reviewer(header_lines: list[str], expect: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    errors = []
    warnings = []
    rev_line = next((l for l in header_lines if l.startswith("Reviewer:")), None)
    if rev_line is not None:
        value = rev_line[len("Reviewer:"):].strip()
        if value != expect:
            errors.append(("reviewer", f"Reviewer is {value!r}, expected {expect!r}"))
    self_line = next((l for l in header_lines if l.startswith("Self-identified:")), None)
    if self_line is not None:
        value = self_line[len("Self-identified:"):].strip()
        if value != expect:
            warnings.append(("reviewer", f"Self-identified is {value!r}, differs from --expect {expect!r}"))
    return errors, warnings


def check_placeholder(lines: list[str]) -> list[tuple[str, str]]:
    errors = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned = INLINE_CODE_RE.sub("", line)
        for _ in PLACEHOLDER_RE.finditer(cleaned):
            errors.append(("placeholder", f"leftover placeholder in line: {line.strip()!r}"))
    return errors


def check_entity(lines: list[str]) -> list[tuple[str, str]]:
    """Entities in prose are a rendering bug; inside fences or inline code they are quoted evidence."""
    errors = []
    for line in visible(lines):
        for m in ENTITY_RE.finditer(INLINE_CODE_RE.sub("", line)):
            errors.append(("entity", f"HTML entity found: {m.group(0)!r}"))
    return errors


def check_findings(section_lines: list[str]) -> tuple[list[tuple[str, str]], list[tuple[int, str, str]]]:
    errors = []
    findings = []
    idxs = [i for i, l in enumerate(section_lines) if l.startswith("### ")]
    for pos, i in enumerate(idxs):
        end = idxs[pos + 1] if pos + 1 < len(idxs) else len(section_lines)
        heading = section_lines[i]
        block = section_lines[i:end]
        m = FINDING_HEADING_RE.match(heading)
        if not m:
            errors.append(("finding", f"invalid finding heading: {heading!r}"))
            continue
        num = int(m.group("num"))
        level = m.group("level")
        conf = m.group("conf")
        findings.append((num, level, conf))
        for label in FINDING_BULLETS:
            bl = next((l for l in block if l.strip().startswith(f"- {label}")), None)
            if bl is None:
                errors.append(("finding", f"F{num} missing '- {label}' bullet"))
                continue
            value = bl.strip()[len(f"- {label}"):].strip()
            if label == "Evidence:" and not value:
                # a quote may start on the next line (fenced or indented continuation)
                j = block.index(bl) + 1
                value = "".join(l for l in block[j:j + 2] if l.startswith((" ", "	", "```"))).strip()
            if label == "Evidence:" and not value:
                errors.append(("finding", f"F{num} Evidence bullet is empty"))
            if label == "Where:" and not WHERE_LOC_RE.search(bl):
                errors.append(("finding", f"F{num} Where bullet missing a `path:line` token"))
    return errors, findings


def check_counts(lines: list[str], findings: list[tuple[int, str, str]]) -> list[tuple[str, str]]:
    counts_line = next((l for l in visible(lines) if l.strip().startswith("- Counts:")), None)
    if counts_line is None:
        return [("counts", "missing '- Counts:' line")]
    errors = []
    written = {}
    for label, rgx in COUNT_LABEL_RE.items():
        m = rgx.search(counts_line)
        if not m:
            errors.append(("counts", f"missing {label} count in Counts line"))
            continue
        written[label] = int(m.group(1))
    actual = {"Blocker": 0, "Major": 0, "Minor": 0, "Nit": 0}
    for _, level, _ in findings:
        actual[level] += 1
    actual["Alternatives"] = len([l for l in extract_section(lines, "Better alternatives") if l.startswith("### A")])
    actual["Questions"] = len(
        [l for l in extract_section(lines, "Questions to the author") if l.strip().startswith("- Q")]
    )
    for label in ("Blocker", "Major", "Minor", "Nit", "Alternatives", "Questions"):
        if written.get(label) != actual[label]:
            errors.append(("counts", f"{label} count mismatch: written {written.get(label)}, actual {actual[label]}"))
    return errors


def compute_verdict(findings: list[tuple[int, str, str]]) -> str:
    if any(level == "Blocker" and conf in ("High", "Medium") for _, level, conf in findings):
        return "BLOCK"
    has_major_hm = any(level == "Major" and conf in ("High", "Medium") for _, level, conf in findings)
    blockers_majors = [f for f in findings if f[1] in ("Blocker", "Major")]
    all_low = bool(blockers_majors) and all(conf == "Low" for _, _, conf in blockers_majors)
    if has_major_hm or all_low:
        return "FIX FIRST"
    return "SHIP"


VERDICT_WORDS_RE = re.compile(r"BLOCK|FIX FIRST|SHIP")


def check_verdict(lines: list[str], findings: list[tuple[int, str, str]]) -> list[tuple[str, str]]:
    verdict_line = next((l for l in visible(lines) if l.strip().startswith("- Verdict:")), None)
    if verdict_line is None:
        return [("verdict", "missing '- Verdict:' line")]
    expected = compute_verdict(findings)
    stripped = verdict_line.strip()
    head = stripped[len("- Verdict:"):].split(" — ", 1)[0]
    m = VERDICT_WORDS_RE.search(head)
    written = m.group(0) if m else None
    if written != expected:
        return [("verdict", f"Verdict line does not contain expected {expected!r}: {stripped!r}")]
    return []


def check_alternatives(lines: list[str]) -> list[tuple[str, str]]:
    errors = []
    section = extract_section(lines, "Better alternatives")
    idxs = [i for i, l in enumerate(section) if re.match(r"^### A\d+", l)]
    if not idxs:
        return [("alternatives", "no '### A<n>' heading found")]
    for pos, i in enumerate(idxs):
        end = idxs[pos + 1] if pos + 1 < len(idxs) else len(section)
        block = section[i:end]
        num = re.match(r"^### A(\d+)", section[i]).group(1)
        for label in ALT_BULLETS:
            if not any(l.strip().startswith(f"- {label}") for l in block):
                errors.append(("alternatives", f"A{num} missing '- {label}' bullet"))
    return errors


def check_questions(lines: list[str]) -> list[tuple[str, str]]:
    section = extract_section(lines, "Questions to the author")
    if not any(l.strip().startswith("- Q") for l in section):
        return [("questions", "no '- Q<n>' bullet found")]
    return []


def check_held_up(lines: list[str]) -> list[tuple[str, str]]:
    section = extract_section(lines, "Held up")
    if not any(l.strip().startswith("- ") for l in section):
        return [("held-up", "no bullet found under Held up")]
    return []


def parse_table_rows(section: list[str]) -> list[list[str]]:
    rows = []
    for line in section:
        s = line.strip()
        if not s.startswith("|"):
            continue
        if re.match(r"^\|[\s:-]+\|", s):
            continue
        rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


def check_stress(lines: list[str]) -> tuple[list[tuple[str, str]], list[list[str]]]:
    errors = []
    section = extract_section(lines, "Stress log")
    data_rows = [r for r in parse_table_rows(section) if r and r[0] != "#"]
    qualifying = 0
    for r in data_rows:
        if len(r) < 4:
            continue
        result, how = r[2], r[3]
        if "broke" in result or "held" in result:
            qualifying += 1
            if not re.search(r"\S+:\d+", how):
                errors.append(("stress", f"stress row missing a file:line token in How checked: {r}"))
    if qualifying < 3:
        errors.append(("stress", f"fewer than 3 broke/held rows found ({qualifying})"))
    return errors, data_rows


def check_method(method_value: str | None, data_rows: list[list[str]]) -> list[tuple[str, str]]:
    errors = []
    if method_value == "STATIC":
        for r in data_rows:
            if len(r) < 4:
                continue
            how = r[3]
            if how.startswith("TEST:") or how.startswith("LIVE:"):
                errors.append(("method", f"STATIC method but stress row has {how!r}"))
    return errors


def check_low_conf(lines: list[str], findings: list[tuple[int, str, str]]) -> list[tuple[str, str]]:
    section_text = "\n".join(extract_section(lines, "Not verified"))
    warnings = []
    for num, level, conf in findings:
        if level in ("Blocker", "Major") and conf == "Low" and f"F{num}" not in section_text:
            warnings.append(("low-conf", f"F{num} (Low-confidence {level}) not mentioned in Not verified"))
    return warnings


def check_nit_cap(findings: list[tuple[int, str, str]]) -> list[tuple[str, str]]:
    nits = sum(1 for _, level, _ in findings if level == "Nit")
    if nits > MAX_NITS:
        return [("nit-cap", f"{nits} Nit findings, at most {MAX_NITS} allowed; fold the extras into one")]
    return []


def run_checks(
    lines: list[str], expect: str, dispatcher_method: str | None = None
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    errors: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    errors += check_preamble(lines)
    errors += check_headings(lines)
    header_errors, header_lines = check_header(lines)
    errors += header_errors
    rev_errors, rev_warnings = check_reviewer(header_lines, expect)
    errors += rev_errors
    warnings += rev_warnings
    errors += check_placeholder(lines)
    errors += check_entity(lines)

    findings_errors, findings = check_findings(extract_section(lines, "Findings"))
    errors += findings_errors
    errors += check_counts(lines, findings)
    errors += check_verdict(lines, findings)
    errors += check_alternatives(lines)
    errors += check_questions(lines)
    errors += check_held_up(lines)

    stress_errors, data_rows = check_stress(lines)
    errors += stress_errors
    method_match = re.search(r"Method:\s*(\S+)", "\n".join(header_lines))
    doc_method = method_match.group(1) if method_match else None
    if dispatcher_method is not None and doc_method != dispatcher_method:
        errors.append(("method", f"header says {doc_method}, dispatcher set {dispatcher_method}"))
    method_value = dispatcher_method if dispatcher_method is not None else doc_method
    errors += check_method(method_value, data_rows)
    warnings += check_low_conf(lines, findings)
    warnings += check_nit_cap(findings)

    return errors, warnings


def cmd_check(args: argparse.Namespace) -> int:
    """Validate a review file written from TEMPLATE.md and print FAIL/WARN lines."""
    path = Path(args.file)
    raw = path.read_bytes()
    had_crlf = b"\r\n" in raw
    norm = raw.decode("utf-8").replace("\r\n", "\n")

    if args.stamp and not re.search(r"(?m)^Reviewer:", norm):
        norm = re.sub(r"(?m)^(Self-identified:)", f"Reviewer: {args.expect}\n\\1", norm, count=1)
        out = norm.replace("\n", "\r\n") if had_crlf else norm
        path.write_bytes(out.encode("utf-8"))

    lines = norm.split("\n")
    errors, warnings = run_checks(lines, args.expect, args.method)
    for rule, detail in errors:
        print(f"FAIL: {rule}: {detail}")
    for rule, detail in warnings:
        print(f"WARN: {rule}: {detail}")
    if errors:
        print(f"FAILED ({len(errors)})")
        return 1
    print("OK")
    return 0


# ---------------------------------------------------------------------------
# codex-model
# ---------------------------------------------------------------------------


def cmd_codex_model(args: argparse.Namespace) -> int:
    """Print the top-level model from Codex's config."""
    codex_home = os.environ.get("CODEX_HOME")
    path = (Path(codex_home) if codex_home else Path.home() / ".codex") / "config.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"config file missing: {path}", file=sys.stderr)
        return 2

    for line in text.splitlines():
        if line.strip().startswith("["):
            break
        match = re.match(r'^\s*model\s*=\s*"([^"]+)"', line)
        if match:
            print(match.group(1))
            return 0
    print(f"no top-level model key in {path}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="advocate.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("target", nargs="?", default=None)
    p_build.add_argument("-o", "--out", required=True)
    p_build.add_argument("--kind", choices=["service", "cli", "script", "doc"], default="script")
    p_build.add_argument("--lang", choices=["ko", "en"], default="ko")
    p_build.add_argument("--focus", default=None)
    p_build.add_argument("--method", choices=["STATIC", "TEST", "LIVE"], default="STATIC")
    p_build.add_argument("--max-bytes", type=int, default=400000)
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser("check")
    p_check.add_argument("file")
    p_check.add_argument("--expect", required=True)
    p_check.add_argument("--stamp", action="store_true")
    p_check.add_argument("--method", choices=["STATIC", "TEST", "LIVE"], default=None)
    p_check.set_defaults(func=cmd_check)

    p_codex_model = sub.add_parser("codex-model")
    p_codex_model.set_defaults(func=cmd_codex_model)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

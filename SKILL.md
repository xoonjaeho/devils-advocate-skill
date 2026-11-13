---
name: devils-advocate
description: Adversarial second opinion on a diff, commit range or path — a separate engine (claude / codex) tries to break the change; its fixed-format review is verified against the real files and reported verbatim. Works in Claude Code (`/devils-advocate [target] [--engine claude|codex] [--focus <text>] [--kind …] [--lang ko|en]`) and in Codex (`$devils-advocate` with the same args, or name the skill).
argument-hint: "[target] [--engine claude|codex] [--focus TEXT] [--kind script|cli|service|doc] [--lang ko|en] [--method STATIC|TEST|LIVE]"
---

# /devils-advocate — adversarial review by a separate engine

The orchestrator (you) never writes the review. You build the packet, dispatch one engine, check the result, verify its specific claims, and print it as-is.

## 1. Args

Claude Code: `/devils-advocate [target] [--engine E] [--focus TEXT] [--kind K] [--lang L] [--method M]`. Codex: `$devils-advocate ...` or name the skill; same args.

Host = the product running you. Know it from your own system prompt (`CLAUDECODE=1` in the environment confirms Claude Code); never infer it from which tools exist.

- `target` — a git rev (`HEAD`, `abc123`), a range (`main..HEAD`), or a path. Absent → the working tree: `build` runs `git diff HEAD` itself (lockfiles excluded; empty diff → falls back to `HEAD`). Untracked files are not in that diff — say so in the report, or pass their path as the target. A directory target skips `.gitignore`d files and lockfiles; the packet's Target section lists what was skipped. To review a lockfile, pass its path.
- `--engine` — `claude` · `codex`; default = the host's own engine (claude in Claude Code, codex in Codex) — a fresh session of the same engine is independent. Never switch engines silently; if the chosen one is unavailable, say so and stop.
- `--kind` default `script`; `--lang` default `en`; `--focus` default none; `--method` default `STATIC` (`TEST` only when the repo has a runnable test suite).

### Paths and Python

Shell variables do not persist between the host's tool calls. Resolve each value once, then write the literal value into every later command.

- `<skill>` — the directory holding this SKILL.md (e.g. `~/.claude/skills/devils-advocate` or `~/.agents/skills/devils-advocate`), as an absolute path.
- `<python>` — probe once, use the printed path:

  ```bash
  for c in python3 python py; do "$c" -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>/dev/null && { command -v "$c"; break; }; done
  ```

  No output → Python 3.10+ is missing; report it and stop.
- `<scratch>` — the host's session scratchpad if it gives one; else create it once: `<python> -c "import tempfile; print(tempfile.mkdtemp(prefix='da_'))"` and use that printed path. Delete the directory at the end if you created it.

Run every command below with `PYTHONUTF8=1`.

| engine | host | `check --expect` value (Reviewer stamp) | runs as |
|---|---|---|---|
| claude | Claude Code | `claude-opus` (the `opus` alias, not a pinned id) | `Agent(subagent_type:"general-purpose", model:"opus")`; if the `Agent` tool is unavailable in that session, `run --engine claude` |
| claude | Codex | `claude-opus` | `run --engine claude` |
| codex | either | the `expect:` line `run` prints | `run --engine codex` |

## 2. Build

```bash
cd <repo> && PYTHONUTF8=1 <python> <skill>/scripts/advocate.py build [target] -o <scratch>/tmp_da_packet.md --kind K --lang L --method M [--focus TEXT]
```

Omit `target` for the working tree. Exit 1 = packet too large, git error, or everything was excluded (re-run with the file path); print the stderr line and stop. Emit `tmp: <scratch>/tmp_da_packet.md` on creation.

## 3. Dispatch — one engine, output to a file, foreground

- **claude in Claude Code**: `Agent(subagent_type:"general-purpose", model:"opus", prompt: "Read <abs packet path> and do exactly what it says. Write the finished document to <abs out path> with the Write tool (UTF-8) and reply with the single word done. Do not invoke /devils-advocate or any review skill.")`. The subagent must be a fresh session — never write the review in this conversation (the reviewer must not be the session that wrote the change). Expect value: `claude-opus`.
- **every other case** (`run` does the CLI lookup, login check, sandbox and tool allowlist):

  ```bash
  PYTHONUTF8=1 <python> <skill>/scripts/advocate.py run --engine E --repo <repo> --packet <scratch>/tmp_da_packet.md --out <scratch>/tmp_da_out.md --method M [--allow "Bash(<test cmd> *)"]
  ```

  Foreground; give the host's command timeout the `--timeout` (default 600 s) plus a margin. With `--method TEST`, pass `--allow` for the repo's test command, e.g. `Bash(python -m pytest *)`. With `--method TEST` the codex engine runs with `workspace-write` on the reviewed repo (tests need to write), unlike STATIC's read-only. On success `run` prints one line, `expect: <value>`; that value feeds `check --expect`.
  - Exit 2 unreadable packet or `--out` equal to `--packet` · 3 engine unavailable (CLI missing, codex not logged in or login check timed out, unsafe path for a Windows .cmd shim) · 4 timeout · 5 engine crash · 6 empty output. Report it as such, with the stderr line, and stop. Do not re-dispatch to another engine.
  - From a Codex host the nested run needs network access and access to the `CODEX_HOME` credentials; if the parent session is sandboxed away from them, `run` exits 3 — report and stop.

A timeout, crash, or empty output file is reported as such and ends the run.

## 4. Check

```bash
PYTHONUTF8=1 <python> <skill>/scripts/advocate.py check <scratch>/tmp_da_out.md --expect <expect value> --method M --stamp
```

`--method` is the value you passed to build; the document's own `Method:` line is not trusted.

- Exit 0 → §5. `WARN: reviewer` (Self-identified ≠ Reviewer) is kept in the report line, never treated as failure — models misreport their own id.
- Exit 1 → retry **once** with the same engine: append to the packet

  ```
  ## Checker errors from your previous attempt — fix every line, then output the full document again
  <the FAIL lines verbatim>
  ```

  and dispatch again (same path as §3) to `tmp_da_out2.md`, then check it. Second failure → print the raw document as-is, followed by the check output, and stop. Never patch the document yourself.

## 5. Verify specific claims

For every `### F<n>` heading, read the file at its `Where:` `path:line` **as of the reviewed revision** — `git show <rev>:<path>` for a rev/range target (the right-hand rev), the working tree for a path or no-target run — never the current tree when the target is historical. The claim holds when the Evidence quote, or the code it describes, is at that line (±5 lines). Otherwise append ` ⚠ unverified` to that F heading — never delete it. If a Fix has an `rg: <regex>` line, run it at the reviewed revision (`git grep -nE <regex> <rev>` for a rev/range target, `rg -n <regex>` (or `git grep -nE --untracked <regex>` when `rg` is absent) on the working tree for a path or no-target run) and append ` (rg: <n> hits)` to that F heading. Then recompute the verdict from the verified F headings only, by the rule in `compute_verdict` (`scripts/advocate.py`), and, if it changed, rewrite the `- Verdict:` line as `<new> (was <old>; n finding(s) unverified)`.

## 6. Report

Print the document **in full, verbatim** — no summary, no re-statement, no reordering. After it, one line:

`engine <expect value> · check OK[, WARN: …] · n unverified · packet <bytes> B`

Then delete `<scratch>/tmp_da_*` (and `<scratch>` itself if you created it).

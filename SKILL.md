---
name: devils-advocate
description: Adversarial second opinion on a diff, commit range or path — a separate engine (claude / codex) tries to break the change; its fixed-format review is verified against the real files and reported verbatim. Invoke with `/devils-advocate [target] [--engine claude|codex] [--focus <text>] [--kind …] [--lang ko|en]`.
---

# /devils-advocate — adversarial review by a separate engine

The orchestrator (you) never writes the review. You build the packet, dispatch one engine, check the result, verify its specific claims, and print it as-is.

## 1. Args

`/devils-advocate [target] [--engine E] [--focus TEXT] [--kind K] [--lang L] [--method M]`

- `target` — a git rev (`HEAD`, `abc123`), a range (`main..HEAD`), or a path. Absent → the working tree: `build` runs `git diff HEAD` itself (lockfiles excluded; empty diff → falls back to `HEAD`). Untracked files are not in that diff — say so in the report, or pass their path as the target. A directory target skips `.gitignore`d files and lockfiles; the packet's Target section lists what was skipped. To review a lockfile, pass its path.
- `--engine` — `claude` (default) · `codex`. Never switch engines silently; if the chosen one is unavailable, say so and stop.
- `--kind` default `script`; `--lang` default `ko`; `--focus` default none; `--method` default `STATIC` (`TEST` only when the repo has a runnable test suite).
- `$S` = the session scratchpad. `$SKILL` = this skill's directory (`~/.claude/skills/devils-advocate`). Every command below runs with `PYTHONUTF8=1`.

| engine | `--expect` value (Reviewer stamp) | runs as |
|---|---|---|
| claude | `claude-opus-5-5` | `Agent(subagent_type:"general-purpose", model:"opus")` |
| codex | `$(python "$SKILL/scripts/advocate.py" codex-model)` | `node "$CODEX" task --effort high` |

## 2. Build

```bash
cd <repo> && PYTHONUTF8=1 python "$SKILL/scripts/advocate.py" build [target] -o "$S/tmp_da_packet.md" --kind K --lang L --method M [--focus TEXT]
```

Omit `target` for the working tree. Exit 1 = packet too large, git error, or everything was excluded (re-run with the file path); print the stderr line and stop. Emit `tmp: $S/tmp_da_packet.md` on creation.

## 3. Dispatch — one engine, output to a file, foreground

- **claude**: `Agent(subagent_type:"general-purpose", model:"opus", prompt: "Read <abs packet path> and do exactly what it says. Write the finished document to <abs out path> with the Write tool (UTF-8) and reply with the single word done. Do not invoke /devils-advocate or any review skill.")`. The subagent must be a fresh session — never write the review in this conversation (author-session veto).
- **codex**: `CODEX=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs | sort -V | tail -1); cd <repo> && node "$CODEX" task --effort high < "$S/tmp_da_packet.md" > "$S/tmp_da_out.md"` — foreground, `timeout: 600000`. `task` prints the model's final message verbatim to stdout. Never `--background`.

A timeout, crash, or empty output file is reported as such and ends the run. Do not re-dispatch to another engine.

## 4. Check

```bash
PYTHONUTF8=1 python "$SKILL/scripts/advocate.py" check "$S/tmp_da_out.md" --expect <expect value> --method M --stamp
```

`--method` is the value you passed to build; the document's own `Method:` line is not trusted.

- Exit 0 → §5. `WARN: reviewer` (Self-identified ≠ Reviewer) is kept in the report line, never treated as failure — models misreport their own id.
- Exit 1 → retry **once** with the same engine: append to the packet

  ```
  ## Checker errors from your previous attempt — fix every line, then output the full document again
  <the FAIL lines verbatim>
  ```

  and dispatch again to `tmp_da_out2.md`, then check it. Second failure → print the raw document as-is, followed by the check output, and stop. Never patch the document yourself.

## 5. Verify specific claims

For every `### F<n>` heading, read the file at its `Where:` `path:line` **as of the reviewed revision** — `git show <rev>:<path>` for a rev/range target (the right-hand rev), the working tree for a path or no-target run — never the current tree when the target is historical. The claim holds when the Evidence quote, or the code it describes, is at that line (±5 lines). Otherwise append ` ⚠ unverified` to that F heading — never delete it. If a Fix has an `rg: <regex>` line, run it at the reviewed revision (`git grep -nE <regex> <rev>` for a rev/range target, `rg -n <regex>` on the working tree for a path or no-target run) and append ` (rg: <n> hits)` to that F heading. Then recompute the verdict from the verified F headings only, by the rule in `compute_verdict` (`scripts/advocate.py`), and, if it changed, rewrite the `- Verdict:` line as `<new> (was <old>; n finding(s) unverified)`.

## 6. Report

Print the document **in full, verbatim** — no summary, no re-statement, no reordering. After it, one line:

`engine <expect value> · check OK[, WARN: …] · n unverified · packet <bytes> B`

Then bin `$S/tmp_da_*` (Recycle Bin, never `rm -rf`).

---
name: devils-advocate
description: Adversarial second opinion on a diff, commit range or path — a separate engine (claude / codex / ollama) tries to break the change and writes a fixed-format Devil's Advocate Review; a checker validates the form, the orchestrator verifies every file:line against the real file, and the review is reported verbatim. Invoke with `/devils-advocate [target] [--engine claude|codex|ollama] [--focus <text>] [--kind service|cli|script|doc] [--lang ko|en]`.
---

# /devils-advocate — adversarial review by a separate engine

The orchestrator (you) never writes the review. You build the packet, dispatch one engine, check the result, verify its specific claims, and print it as-is.

## 1. Args

`/devils-advocate [target] [--engine E] [--focus TEXT] [--kind K] [--lang L] [--method M] [--model NAME]`

- `target` — a git rev (`HEAD`, `abc123`), a range (`main..HEAD`), or a path. Absent → the working tree: `git diff HEAD > $S/tmp_target.diff` and use that file (empty diff → fall back to `HEAD`). Untracked files are not in that diff — say so in the report, or pass their path as the target.
- `--engine` — `claude` (default) · `codex` · `ollama`. Never switch engines silently; if the chosen one is unavailable, say so and stop.
- `--kind` default `script`; `--lang` default `ko`; `--focus` default none; `--method` default `STATIC` (`TEST` only for claude/codex when the repo has a runnable test suite — ollama is always STATIC).
- `$S` = the session scratchpad. `$SKILL` = this skill's directory (`~/.claude/skills/devils-advocate`). Every command below runs with `PYTHONUTF8=1`.

| engine | `--expect` value (Reviewer stamp) | runs as |
|---|---|---|
| claude | `claude-opus-5` | `Agent(subagent_type:"general-purpose", model:"opus")` |
| codex | `gpt-6-astra` | `node "$CODEX" task --effort high` |
| ollama | `kimi-k3:cloud` (or `--model`) | `python "$OLLAMA" run --think` |

ollama default is kimi-k3:cloud, not glm-5.3:cloud: on a ~50 KB packet glm spends its whole output budget reasoning and never emits the document (0/3 in the dry run); kimi returns it in ~8 min.

## 2. Build

```bash
cd <repo> && PYTHONUTF8=1 python "$SKILL/scripts/advocate.py" build <target> -o "$S/tmp_da_packet.md" --kind K --lang L --method M [--focus TEXT]
```

Exit 1 = packet too large or git error; print the stderr line and stop. Emit `tmp: $S/tmp_da_packet.md` on creation.

## 3. Dispatch — one engine, output to a file, foreground

- **claude**: `Agent(subagent_type:"general-purpose", model:"opus", prompt: "Read <abs packet path> and do exactly what it says. Write the finished document to <abs out path> with the Write tool (UTF-8) and reply with the single word done. Do not invoke /devils-advocate or any review skill.")`. The subagent must be a fresh session — never write the review in this conversation (author-session veto).
- **codex**: `CODEX=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs | sort -V | tail -1); cd <repo> && node "$CODEX" task --effort high < "$S/tmp_da_packet.md" > "$S/tmp_da_out.md"` — foreground, `timeout: 600000`. `task` prints the model's final message verbatim to stdout. Never `--background`.
- **ollama**: `OLLAMA=<ollama-cc-plugin>/plugins/ollama/scripts/ollama_companion.py; [ -f "$OLLAMA" ] || OLLAMA=$(ls ~/.claude/plugins/cache/ollama-cc/ollama/*/scripts/ollama_companion.py | sort -V | tail -1); PYTHONUTF8=1 OLLAMA_CC_MODEL=<model> python "$OLLAMA" run --think --timeout 600 < "$S/tmp_da_packet.md" > "$S/tmp_da_out.md"`. `PYTHONUTF8=1` is mandatory (cp949 stdin mangles the packet). Text only — never include images.

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

For every `### F<n>` heading, read the file at its `Where:` `path:line` **as of the reviewed revision** — `git show <rev>:<path>` for a rev/range target (the right-hand rev), the working tree for a path target — never the current tree when the target is historical. The claim holds when the Evidence quote, or the code it describes, is at that line (±5 lines). Otherwise append ` ⚠ unverified` to that F heading — never delete it. Then recompute the verdict from the verified F headings only (BLOCK: Blocker with confidence ≥ Medium · FIX FIRST: Major with confidence ≥ Medium, or only Low-confidence Blocker/Major · SHIP: neither) and, if it changed, rewrite the `- Verdict:` line as `<new> (was <old>; n finding(s) unverified)`.

## 6. Report

Print the document **in full, verbatim** — no summary, no re-statement, no reordering. After it, one line:

`engine <expect value> · check OK[, WARN: …] · n unverified · packet <bytes> B`

Then bin `$S/tmp_da_*` (Recycle Bin, never `rm -rf`).

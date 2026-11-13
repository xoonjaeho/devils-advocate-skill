# 😈 /devils-advocate — adversarial review by a separate engine

An agent skill for Claude Code and Codex CLI. A second engine (Claude or Codex) tries to break a change and writes a fixed-format **Devil's Advocate Review**; a stdlib checker validates the form, the orchestrating session verifies every `file:line` against the real file, and the review is reported verbatim — never summarised, never written by the session that made the change.

## Quick start

```
/devils-advocate                       # working tree vs HEAD, host's own engine (claude → opus)
/devils-advocate HEAD --engine codex   # last commit, reviewed by codex's configured default model
/devils-advocate main..HEAD --engine codex --kind service --focus "rollback"
/devils-advocate src/api/ --lang ko
```

In Codex use `$devils-advocate` instead of `/devils-advocate`.

Args: `[target] [--engine claude|codex] [--focus TEXT] [--kind service|cli|script|doc] [--lang ko|en] [--method STATIC|TEST|LIVE]`. Defaults: working tree · host's engine · kind `script` · lang `en` · method `STATIC`.

## What you get

One document, headings fixed in English, body in `--lang`:

| Section | Holds |
|---|---|
| Overview | what the change does in the reviewer's own words · Verdict `⛔ BLOCK / 🔧 FIX FIRST / ✅ SHIP` · Counts · what held |
| Stress log | core four (trust-boundary input · failure & rollback · tests-that-actually-fail · over-engineering) + kind-keyed rows, each `💥 broke → F# / 🛡️ held / ➖ n/a: reason` |
| Findings | `F# · Blocker/Major/Minor/Nit · confidence High/Medium/Low` with Where · Claim · Evidence · Impact · Fix |
| Better alternatives | `A#` with Current · Proposed · Better on · Costs · Evidence |
| Questions to the author | each says which answer would change the verdict |
| Held up · Not verified | what was done well · the boundary of what was checked |

The verdict is recomputed by the checker from the findings (rule: `compute_verdict` in `scripts/advocate.py`) — the engine cannot declare `SHIP` over an unaddressed Blocker. `Reviewer:` is stamped by the dispatch path; `Self-identified:` is the model's own claim and only ever a warning.

## How it works

```
target (diff / path / range)
   └─ scripts/advocate.py build   → packet.md  (packet.md + fenced target + TEMPLATE.md, header pre-filled)
        └─ ONE engine, fresh session, output to a file
             claude : Agent(model: opus) in Claude Code, `claude -p --model opus` in Codex → claude-opus
             codex  : codex exec -s read-only < packet → codex's default model (advocate.py codex-model)
                      (with --method TEST the sandbox is workspace-write on the reviewed repo, since tests need to write)
              └─ scripts/advocate.py check --expect <engine> --method M --stamp
                   fail → same engine once more with the FAIL lines appended → else raw output + errors
                   pass → session verifies every F# Where/Evidence at the reviewed revision
                          unverified F# keep their text, tagged ⚠ unverified; verdict recomputed
                            └─ printed in full, verbatim
```

## Layout

```
SKILL.md              orchestration: args, build, dispatch, check, verify, report
TEMPLATE.md           the output form — field names are frozen (checker + tests depend on them)
packet.md             engine-neutral reviewer prompt (rules, stress scenarios, severity, evidence)
scripts/advocate.py   build | check — stdlib only, regex parsing
tests/test_check.py   one failing fixture per checker rule + one passing fixture
```

## Install

```
# Claude Code
git clone https://github.com/xoonjaeho/devils-advocate-skill.git ~/.claude/skills/devils-advocate
# Codex
git clone https://github.com/xoonjaeho/devils-advocate-skill.git ~/.agents/skills/devils-advocate
```

Requires Python 3.10+ (`run` reads Codex's `config.toml` exactly with `tomllib` on 3.11+; 3.10 works with a regex fallback) (`python3` on macOS/Linux, `python` on Windows; the skill picks whichever exists) and git. Engine CLIs: Claude Code (`claude`) and/or Codex CLI (`codex`, logged in). The codex engine needs no plugin. The claude engine runs with `--tools Read,Grep,Glob,Bash` and read-only git patterns; Bash allow rules in your own Claude settings still apply.

## Tests

```
PYTHONUTF8=1 python -m pytest tests -q
```

## License

MIT — see [LICENSE](LICENSE).

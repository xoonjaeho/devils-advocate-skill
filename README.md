# 😈 /devils-advocate — adversarial review by a separate engine

A Claude Code skill. A second engine (Claude, Codex, or an ollama cloud model) tries to break a change and writes a fixed-format **Devil's Advocate Review**; a stdlib checker validates the form, the orchestrating session verifies every `file:line` against the real file, and the review is reported verbatim — never summarised, never written by the session that made the change.

## Quick start

```
/devils-advocate                       # working tree vs HEAD, engine claude (opus)
/devils-advocate HEAD --engine codex   # last commit, reviewed by gpt-6-sol
/devils-advocate main..HEAD --engine ollama --kind service --focus "rollback"
/devils-advocate src/api/ --lang en
```

Args: `[target] [--engine claude|codex|ollama] [--focus TEXT] [--kind service|cli|script|doc] [--lang ko|en] [--method STATIC|TEST|LIVE] [--model NAME]`. Defaults: working tree · claude · kind `script` · lang `ko` · method `STATIC`.

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

The verdict is recomputed by the checker from the findings — the engine cannot declare `SHIP` over an unaddressed Blocker. `Reviewer:` is stamped by the dispatch path; `Self-identified:` is the model's own claim and only ever a warning.

## How it works

```
target (diff / path / range)
   └─ scripts/advocate.py build   → packet.md  (packet.md + fenced target + TEMPLATE.md, header pre-filled)
        └─ ONE engine, fresh session, output to a file
             claude : Agent(model: opus)            → claude-opus-5-5
             codex  : codex-companion task < packet → gpt-6-sol
             ollama : ollama_companion run < packet → kimi-k3:cloud    (STATIC only)
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

Copy the directory to `~/.claude/skills/devils-advocate/` (the same way as the other skills in this repository). Requires Python 3.10+. Engines are optional: `codex` needs the openai-codex plugin, `ollama` the ollama-cc plugin with a signed-in cloud model.

## Tests

```
PYTHONUTF8=1 python -m pytest tests -q
```

## License

MIT — see [LICENSE](LICENSE).

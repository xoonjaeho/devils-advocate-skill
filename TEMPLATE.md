# 😈 Devil's Advocate Review — <target one-liner>

Reviewer: <stamped by SKILL.md from the dispatch path — claude-opus / codex's configured model>
Self-identified: <the model id you believe you are — written by the engine, never checked, mismatch = warning>
Target: <commit range | path | PR>   Base: <sha>   Date: <YYYY-MM-DD HH:mm>
Scope: <files reviewed / files skipped and why>   Focus: <--focus or "none">
Method: STATIC | TEST | LIVE   <stamped by build>   Kind: service | cli | script | doc   Lang: ko | en   <body language; labels stay English>

## 📋 Overview
- What it does: <2–3 lines in the reviewer's own words — proves the reviewer read it>
- Verdict: ⛔ BLOCK | 🔧 FIX FIRST | ✅ SHIP — <one-line reason; check recomputes it from the F# headings>
- Counts: 🔴 Blocker n · 🟠 Major n · 🟡 Minor n · 🟢 Nit n · 💡 Alternatives n · ❓ Questions n   <check recounts; a mismatch fails>
- What held: 🛡️ <scenarios that failed to break it, one line — absence of findings is a claim too>

## 🧪 Stress log
| # | Scenario | Result | How checked |
|---|----------|--------|-------------|
| S1 | <e.g. concurrent writers on the same key> | 💥 broke → F1 | TEST: <cmd> |
| S2 | <e.g. rollback after partial write> | 🛡️ held | STATIC: <file:line> |
| S3 | <e.g. auth/tenant> | ➖ n/a: <reason> | — |
<core 4 always: trust-boundary input · failure & rollback · tests-that-actually-fail · over-engineering.
 Kind-keyed rows (from packet.md's table): service → concurrency/races · partial writes · version skew · auth/tenant · resource limits · observability;
 cli → resource limits · time/locale · partial writes; script → partial writes · resource limits; doc → contradictory instructions · unverifiable acceptance criteria.
 At least 3 rows must be broke/held with a file:line; an n/a reason must cite the target's structure ("single-process CLI, no shared state"), never taste>

## 🔍 Findings
### F1 · 🔴 Blocker · confidence High · <title>
- Where: `<file>:<line>`
- Claim: <what is wrong, one sentence>
- Evidence: <verbatim quote ≤5 lines, repro command + output, or a citation — never "looks wrong">
- Impact: <what a user/operator sees when it fails>
- Fix: <concrete change; "see A1" if an alternative covers it>

<level glyphs are fixed: 🔴 Blocker · 🟠 Major · 🟡 Minor · 🟢 Nit — the checker matches the word, the glyph is for the eye>

### F2 · 🟠 Major · confidence Medium · <title>
…

## 💡 Better alternatives
### A1 · replaces F1 | design-wide · <title>
- Current: <what the change does now>
- Proposed: <the alternative, concrete enough to implement>
- Better on: correctness | performance | complexity | operability | cost — <which, and by how much if measurable>
- Costs: <what it gives up; migration; risk>
- Evidence: <benchmark, reference implementation, doc link, or prior art in this repo>

## ❓ Questions to the author
- Q1 (re F1): <question> — <which answer would change the verdict>
- Q2 (re design): <question the reviewer could not settle from the code>

## 👍 Held up
- <1–3 things done well, each with a location — keeps the attack honest>

## ⚠️ Not verified
- <claims the reviewer could not check and why — missing env, no test harness, needs LIVE>

---
description: Author a new legend from a famous name or a plain-English strategy, then lint + audition it
argument-hint: <name | strategy description>
allowed-tools: mcp__MBT__get_ohlcv, mcp__tvremix__get_ohlcv, Read, Write, Bash
---
Forge a new legend from **$ARGUMENTS** and admit it to the user's roster. Works on a
slash command or plain English ("make a trader who buys liquidity sweeps"); see
`CLAUDE.md`. **Infer-first**: draft everything you can, ask only for true gaps.

## 1. Classify the input
- A **named figure** (e.g. "ICT", "Al Brooks", "Minervini") → use the documented
  **public methodology**. Frame it as a *strategy profile*, not an impersonation of a
  person.
- A **strategy description** (including the user's own) → encode exactly what they wrote.

## 2. Draft the spec (format = `tlc/legends/<id>.md`, see `PRD.md` §1.7)
Pick a lowercase `id` (letters/digits/underscore; don't collide with a core legend
unless the user wants to override one). Write frontmatter
(`id, display_name, tf_scope, default_anchor, regime_strengths`) + sections:
**Identity, Method, Timeframe rules, Vote rules, Output** (copy the shape of
`tlc/legends/wyckoff.md`). The Vote rules MUST state LONG/SHORT/FLAT conditions, an
**invalidation rule** (what proves it wrong — this becomes the stop), and the
**conviction** drivers. Output section points at `_single_legend_flow.md`.

## 3. Fill only the gaps
Ask the user **only** for fields you genuinely cannot infer — most often the
invalidation rule. Keep it to one or two short questions; infer the rest.

## 4. Lint (hard gate)
Write the draft to `my_legends/<id>.md`, then:
`python3 -m tlc.spec_lint my_legends/<id>.md`
If it reports errors, fix them and re-lint until clean. A spec with no invalidation
rule cannot pass — that's intentional (it must be scoreable).

## 5. Audition (live smoke-test)
Run the legend once via the single-legend flow (`tlc/legends/_single_legend_flow.md`)
on a sensible symbol/timeframe for its method (resolve the platform per `CLAUDE.md`).
Validate the resulting ballot:
`python3 -c "from tlc.ballot import validate_ballot; import json,sys; print(validate_ballot(json.load(sys.stdin)) or 'OK')" < ballot.json`
It must return `OK` (a schema-valid LONG/SHORT/FLAT ballot). If invalid, adjust the
spec and repeat. Optionally show a quick read of how it voted.

## 6. Save + offer to group
The spec is already at `my_legends/<id>.md` (gitignored — the user's edge stays theirs).
Confirm it's admitted, then offer to add it to a council:
"Add `<id>` to a council? (new one, or an existing roster)". If the user is clearly
mid-"build a council" flow, add it to that council; otherwise leave standalone and ask.
Create/append rosters with `/council` (`python3 -m tlc.council new <name> <id…>`).

---
description: Create, list, or inspect a custom council (roster of legends)
argument-hint: new <name> <id…> | list | show <name>
allowed-tools: Read, Write, Bash
---
Manage custom councils from **$ARGUMENTS**. A council is a named roster file
(`councils/<name>.yaml`) — which legends vote, plus optional Chairman settings.
Plain English works too ("make a council 'scalp' with wyckoff, livermore, ict_ob");
see `CLAUDE.md`. Members resolve `my_legends/<id>.md` first, then `tlc/legends/<id>.md`.

## Create — `new <name> <id…>`
1. Confirm every member exists: `python3 -m tlc.council show standard` lists the core
   ids; the user's custom ids live in `my_legends/`. If a named member doesn't exist
   yet, offer to forge it first with `/forge-legend`.
2. Write the roster (validates member resolution; refuses unknown members):
   `python3 -m tlc.council new <name> <id> <id> … [--threshold 0.6]`
   Or write `councils/<name>.yaml` directly (schema in `PRD.md` §1.11). Default
   threshold is the config value (0.65) unless the user sets one.
3. Show the result and tell them how to run it:
   `convene the <name> council on <symbol>`.

## List — `list`
`python3 -m tlc.council list` — the default `standard` council plus any custom rosters.

## Show — `show <name>`
`python3 -m tlc.council show <name>` — resolves members (core vs my_legends), shows the
effective threshold/weights, and warns about any custom legend that shadows a core one.

Keep councils small and **diverse** — five trend-followers just echo each other. A good
roster mixes schools (e.g. a structure read, a momentum voice, and a counter-trend seat).

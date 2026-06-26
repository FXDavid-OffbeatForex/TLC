# my_legends/

Your custom legends live here — author them with `/forge-legend` (from a famous
name or a plain-English strategy description). **This directory is gitignored**
(except the shipped example), so your strategies stay yours and never leak into a
fork or PR.

- A legend here is a spec file `<id>.md` in the format of [tlc/legends/](../tlc/legends/)
  (see [ict_ob.md](ict_ob.md) for a worked example).
- Ids here resolve **before** the canonical legends, so you can also shadow/override
  a core legend by naming a file after it.
- Every legend must pass `python3 -m tlc.spec_lint my_legends/<id>.md` (and a live
  audition) before it can vote.

Group legends into a roster under [councils/](../councils/) and run it with
`/convene <symbol> --council <name>`.

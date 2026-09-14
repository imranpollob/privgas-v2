# data/private/

This directory holds any input or intermediate data that must not leave the
local machine: real (non-test) keys, unredacted logs, anything not yet
cleared for publication.

**Everything under this directory except this README and `.gitkeep` is
gitignored** (see `.gitignore`). If you need a file here to be committed,
that is a decision to make explicitly and document in
`docs/decision-log.md` — do not just force-add it.

Nothing should read from `data/private/` in a way that leaks its contents
into `data/public/`, `results/`, or `figures/` without an explicit,
reviewed redaction step.

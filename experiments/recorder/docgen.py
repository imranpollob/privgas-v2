"""Generate the field tables in docs/experiment-schema.md from the schemas.

The tables are generated rather than hand-maintained so the documentation
cannot drift from the validator: ``test_docs_in_sync.py`` regenerates them and
fails if the file on disk differs. Prose around the tables is written by hand;
only the regions between the BEGIN/END markers are machine-owned.

    python3 -m experiments.recorder.docgen --check     # verify, exit 1 if stale
    python3 -m experiments.recorder.docgen --write     # rewrite the tables
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .provenance import repo_root
from .validate import describe_schema
from .version import STREAMS

DOC_PATH = "docs/experiment-schema.md"

BEGIN = "<!-- BEGIN GENERATED: {stream} -->"
END = "<!-- END GENERATED: {stream} -->"

EMPTY_SEMANTICS = {
    (False, False): "required",
    (True, False): "`null` ok",
    (False, True): "`not_applicable` ok",
    (True, True): "`null` / `not_applicable` ok",
}


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def table_for(stream: str) -> str:
    lines = [
        "| Field | Class | Tier | Empty value | Meaning |",
        "|-------|-------|------|-------------|---------|",
    ]
    for f in describe_schema(stream):
        empty = EMPTY_SEMANTICS[(f["nullable"], f["not_applicable_allowed"])]
        tier = f["observer_tier"]
        tier = "—" if tier == "none" else tier
        lines.append(
            f"| `{f['field']}` | {f['classification']} | {tier} | {empty} | "
            f"{_escape(f['doc'])} |")
    return "\n".join(lines)


def render(text: str) -> str:
    for stream in STREAMS:
        begin, end = BEGIN.format(stream=stream), END.format(stream=stream)
        start = text.find(begin)
        stop = text.find(end)
        if start == -1 or stop == -1:
            raise SystemExit(
                f"{DOC_PATH} is missing the {begin} / {end} markers for the "
                f"{stream} stream")
        text = (text[:start + len(begin)] + "\n\n" + table_for(stream) + "\n\n"
                + text[stop:])
    return text


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else repo_root()
    path = root / DOC_PATH
    current = path.read_text(encoding="utf-8")
    updated = render(current)

    if args.write:
        if updated != current:
            path.write_text(updated, encoding="utf-8")
            print(f"updated {DOC_PATH}")
        else:
            print(f"{DOC_PATH} already up to date")
        return 0

    if updated != current:
        print(f"{DOC_PATH} is out of date with the schemas. Run:\n"
              "  python3 -m experiments.recorder.docgen --write",
              file=sys.stderr)
        return 1
    print(f"{DOC_PATH} matches the schemas")
    return 0


if __name__ == "__main__":
    sys.exit(main())

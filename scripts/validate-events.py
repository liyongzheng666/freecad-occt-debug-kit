#!/usr/bin/env python3
# =====================================================================
# validate-events — check every line of a session's events.ndjson against the
# Print protocol event schema (tools/Print/protocol/event.schema.json).
#
# Used by the occ-mesh-daemon offline test (docs/occ-mesh-daemon-plan.md §6) and
# handy any time you hand-edit or generate events: it parses each NDJSON line
# and reports the first schema violation per line, so a malformed `update`/
# `defect`/`note` is caught before the Bridge/viewer ever sees it.
#
#   Usage:
#     scripts/validate-events.py [EVENTS.ndjson] [--session DIR] [--schema PATH]
#       EVENTS    path to an events.ndjson (default: <session>/events.ndjson)
#       --session session dir (default: $OCC_DEBUG_SESSION or .occ-debug/sessions/dev)
#       --schema  schema file (default: tools/Print/protocol/event.schema.json)
#
#   Exit 0 if every line validates, 1 if any line fails, 2 on a usage error.
#
# Requires `jsonschema` (Draft 2020-12). Stdlib otherwise.
# =====================================================================
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = REPO_ROOT / "tools" / "Print" / "protocol" / "event.schema.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate events.ndjson against the Print event schema.")
    ap.add_argument("events", nargs="?", default=None, help="events.ndjson (default: <session>/events.ndjson)")
    default_session = os.environ.get("OCC_DEBUG_SESSION", ".occ-debug/sessions/dev")
    ap.add_argument("--session", default=default_session, help="session dir (default: $OCC_DEBUG_SESSION or .occ-debug/sessions/dev)")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="event schema JSON")
    ap.add_argument("--quiet", action="store_true", help="only print on failure")
    args = ap.parse_args(argv)

    try:
        import jsonschema
    except ImportError:
        sys.stderr.write("validate-events: needs `pip install jsonschema` (Draft 2020-12)\n")
        return 2

    events_path = Path(args.events) if args.events else Path(args.session) / "events.ndjson"
    if not events_path.exists():
        sys.stderr.write(f"validate-events: no such file: {events_path}\n")
        return 2

    try:
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"validate-events: cannot load schema {args.schema}: {exc}\n")
        return 2
    validator = jsonschema.Draft202012Validator(schema)

    total = 0
    failures = 0
    for lineno, raw in enumerate(events_path.open(encoding="utf-8"), 1):
        raw = raw.strip()
        if not raw:
            continue
        total += 1
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            failures += 1
            print(f"{events_path}:{lineno}: invalid JSON: {exc}")
            continue
        errors = sorted(validator.iter_errors(event), key=lambda e: list(e.path))
        if errors:
            failures += 1
            err = errors[0]
            where = "/".join(str(p) for p in err.path) or "(root)"
            tag = f"{event.get('op', '?')} seq={event.get('seq', '?')}"
            print(f"{events_path}:{lineno}: [{tag}] {where}: {err.message}")

    if failures:
        print(f"validate-events: {failures}/{total} event(s) FAILED schema validation")
        return 1
    if not args.quiet:
        print(f"validate-events: OK — {total} event(s) valid ({events_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

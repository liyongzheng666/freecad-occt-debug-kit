#!/usr/bin/env python3
# =====================================================================
# Fake OCC debug session producer (linkage slice C).
#
# Writes a Print-protocol Session directory and appends geometry debug
# events to events.ndjson one atomic line at a time, so the Bridge's
# tail->SSE path and the viewer's live ingestion can be exercised WITHOUT
# the C++ Capture library existing yet.
#
# Contract (see docs/print-linkage-tech-decisions.md):
#   - <session>/events.ndjson : one complete JSON event per line.
#   - Each line is written atomically (single write of "<json>\n").
#   - Events mirror viewer/src/sample/sampleEvents.ts, only inline
#     geometry kinds (no asset/shape/face) for the first slice.
#
#   Usage:
#     scripts/fake-occ-session.py [--session DIR] [--interval SECONDS]
#                                 [--once] [--append]
#
#   Defaults: session = $OCC_DEBUG_SESSION or .occ-debug/sessions/dev
# =====================================================================
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
SESSION_ID = "dev-fake-0001"
RUN_ID = "run-0001"

# Inline-geometry events equivalent to the viewer's sampleEvents, plus a
# couple extra kinds (vector, point_set) to exercise more renderers.
EVENTS = [
    {
        "op": "add",
        "id": "baseline/body-bounds",
        "group": "baseline/Body",
        "kind": "bbox",
        "label": "Body 基准包围盒",
        "geometry": {"min": [-5, -5, 0], "max": [5, 5, 10]},
        "style": {"color": "#858d82", "opacity": 0.62, "protected": True},
        "topology_ref": {"freecad_object": "Body", "shape_type": "SOLID", "occurrence_path": "Body/Tip"},
        "metadata": {"producer": "fake-session"},
    },
    {
        "op": "add",
        "id": "fillet/input/edge-3",
        "group": "fillet/selected-edges",
        "kind": "edge",
        "label": "选中边 Edge3",
        "geometry": {"points": [[5, -5, 0], [5, -5, 10]]},
        "style": {"color": "#e0a34e", "line_width": 2},
        "source": {
            "file": "src/BRepFilletAPI/BRepFilletAPI_MakeFillet.cxx",
            "line": 527,
            "function": "BRepFilletAPI_MakeFillet::Build",
            "phase": "input",
        },
        "topology_ref": {
            "freecad_object": "Pad",
            "freecad_element": "Edge3",
            "occurrence_path": "Body/Pad/Solid1/Edge3",
            "shape_type": "EDGE",
            "orientation": "FORWARD",
        },
        "metadata": {"producer": "fake-session", "radius": 2, "tolerance": 1e-7, "curve_type": "Geom_Line"},
    },
    {
        "op": "add",
        "id": "fillet/stripe-1/spine",
        "group": "fillet/stripe/1/spine",
        "kind": "polyline",
        "label": "Stripe 1 Spine",
        "geometry": {"points": [[5, -5, 0], [5, -5, 3], [5, -5, 7], [5, -5, 10]]},
        "style": {"color": "#78b6a3", "line_width": 2},
        "source": {
            "file": "src/ChFi3d/ChFi3d_Builder.cxx",
            "line": 239,
            "function": "ChFi3d_Builder::Compute",
            "phase": "perform-set-of-surface",
        },
        "metadata": {"producer": "fake-session", "stripe_index": 1, "first_parameter": 0, "last_parameter": 10},
    },
    {
        "op": "add",
        "id": "fillet/stripe-1/common-point-1",
        "group": "fillet/stripe/1/common-points",
        "kind": "point",
        "label": "公共点 P1",
        "geometry": {"position": [5, -5, 3]},
        "style": {"color": "#e8bd6b", "size": 0.28, "depth_mode": "xray"},
        "source": {
            "file": "src/ChFi3d/ChFi3d_Builder_0.cxx",
            "line": 1722,
            "function": "ChFi3d_Builder::ComputeData",
            "phase": "compute-data",
        },
        "metadata": {"producer": "fake-session", "tolerance": 0.0001, "uv_on_s1": [0.25, 0.5], "uv_on_s2": [0.75, 0.5]},
    },
    {
        "op": "add",
        "id": "fillet/stripe-1/normal-1",
        "group": "fillet/stripe/1/common-points",
        "kind": "vector",
        "label": "P1 法向",
        "geometry": {"origin": [5, -5, 3], "direction": [1, 0, 0], "length": 2.5},
        "style": {"color": "#d6a55d"},
        "metadata": {"producer": "fake-session"},
    },
    {
        "op": "add",
        "id": "fillet/stripe-1/section-samples",
        "group": "fillet/stripe/1/sections",
        "kind": "point_set",
        "label": "截面采样点",
        "geometry": {"positions": [[5, -5, 1], [5, -5, 4], [5, -5, 6], [5, -5, 9]]},
        "style": {"color": "#9ac6b6", "size": 6},
        "metadata": {"producer": "fake-session"},
    },
    {
        "op": "run_end",
        "status": "succeeded",
        "summary": {"entities": 6, "note": "fake session complete"},
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def write_manifest(session: Path) -> None:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "created_at": now_iso(),
        "document": "fake-problem.FCStd",
        "target_object": "Fillet",
        "unit": "mm",
        "coordinate_system": "right_handed_z_up",
        "occt_version": "7.8.1",
    }
    (session / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def append_line(events_path: Path, event: dict, seq: int) -> None:
    """Append one complete event as a single atomic write."""
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "run_id": RUN_ID,
        "seq": seq,
        "timestamp_ns": time.time_ns(),
        **event,
    }
    line = json.dumps(envelope, ensure_ascii=False) + "\n"
    # One write() of the full line keeps the Bridge from ever reading a
    # half-written record (contract §3.4).
    with open(events_path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake OCC debug session producer (linkage slice C).")
    default_session = os.environ.get("OCC_DEBUG_SESSION", ".occ-debug/sessions/dev")
    parser.add_argument("--session", default=default_session, help="Session directory (default: $OCC_DEBUG_SESSION or .occ-debug/sessions/dev)")
    parser.add_argument("--interval", type=float, default=0.8, help="Seconds between appended events in stream mode (default: 0.8)")
    parser.add_argument("--once", action="store_true", help="Write all events immediately, no delay")
    parser.add_argument("--append", action="store_true", help="Append to an existing events.ndjson instead of truncating")
    args = parser.parse_args()

    session = Path(args.session)
    (session / "assets").mkdir(parents=True, exist_ok=True)
    events_path = session / "events.ndjson"

    if not args.append:
        events_path.write_text("", encoding="utf-8")
    write_manifest(session)

    # Continue seq after the existing line count when appending.
    start_seq = 1
    if args.append and events_path.exists():
        start_seq = sum(1 for _ in events_path.open(encoding="utf-8")) + 1

    print(f"[fake-session] session={session}")
    print(f"[fake-session] events={events_path}  mode={'once' if args.once else 'stream'}  start_seq={start_seq}")

    for index, event in enumerate(EVENTS):
        seq = start_seq + index
        append_line(events_path, event, seq)
        label = event.get("label", event["op"])
        print(f"[fake-session] seq={seq} {event['op']:<8} {label}")
        if not args.once and index < len(EVENTS) - 1:
            time.sleep(args.interval)

    print(f"[fake-session] done: {len(EVENTS)} events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

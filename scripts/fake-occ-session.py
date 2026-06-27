#!/usr/bin/env python3
# =====================================================================
# Fake OCC debug session producer (linkage slice C).
#
# Writes a Print-protocol Session directory and appends geometry debug
# events to events.ndjson one atomic line at a time, so the Bridge's
# tail->SSE path and the viewer's live ingestion can be exercised WITHOUT
# the C++ Capture library existing yet.
#
# Reset semantics (linkage doc §8 H2 / boundary-review A group):
#   - A "reload" is NOT a physical truncate. Truncating breaks already
#     connected viewers (stale tail offset) and collides with the reducer's
#     monotonic per-run seq + unique-id guards.
#   - Instead, a reset APPENDS a `clear_scene` event under a NEW run_id and
#     re-emits the debug objects. The protected baseline is emitted once and
#     persists across runs. Connected viewers reload with no refresh.
#
#   Default behavior:
#     - empty/new session  -> fresh run (baseline + debug), run-0001
#     - existing session   -> reset run (clear_scene + debug), run-000N+1
#     --fresh forces a brand-new session file (truncates).
#
#   Usage:
#     scripts/fake-occ-session.py [--session DIR] [--interval SECONDS]
#                                 [--once] [--fresh]
#     scripts/fake-occ-session.py [--session DIR] \
#                                 --emit-shape-asset run-0001/shape-7.brep
#
#   --emit-shape-asset REL  Offline driver for the occ-mesh-daemon path
#     (occ-mesh-daemon-plan.md §6): append a single placeholder `add` event
#     (kind:"shape", occt-brep asset referencing REL, a bbox geometry
#     placeholder) under a fixed run_id, so the daemon can associate the brep
#     with an entity id and upgrade it to a real mesh. The run_id is derived
#     from REL's leading "run-NNNN/" segment (default run-0001); the entity id
#     is the brep's stem (e.g. "shape-7"). Append-only, never truncates.
#
#   Defaults: session = $OCC_DEBUG_SESSION or .occ-debug/sessions/dev
# =====================================================================
import argparse
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
SESSION_ID = "dev-fake-0001"
RUN_RE = re.compile(r"^run-(\d+)$")

# Emitted once per session and protected; persists across resets.
BASELINE_EVENTS = [
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
]

# Re-emitted on every run (cleared by clear_scene first on a reset).
DEBUG_EVENTS = [
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
]

RUN_END_EVENT = {"op": "run_end", "status": "succeeded", "summary": {"note": "fake run complete"}}
CLEAR_SCENE_EVENT = {"op": "clear_scene", "metadata": {"producer": "fake-session", "reason": "new run"}}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def ensure_manifest(session: Path) -> None:
    if (session / "manifest.json").exists():
        return
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


def scan_runs(events_path: Path) -> int:
    """Return the highest run number already present in events.ndjson (0 if none)."""
    if not events_path.exists():
        return 0
    highest = 0
    for raw in events_path.open(encoding="utf-8"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            run_id = json.loads(raw).get("run_id", "")
        except json.JSONDecodeError:
            continue
        match = RUN_RE.match(run_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def append_line(events_path: Path, event: dict, run_id: str, seq: int) -> None:
    """Append one complete event as a single atomic write (contract §3.4).

    flock(LOCK_EX) wraps the write so the whole line can never byte-interleave
    with a concurrent writer (e.g. occ-mesh-daemon appending update/defect
    events to the same file; risk N4).
    """
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "run_id": run_id,
        "seq": seq,
        "timestamp_ns": time.time_ns(),
        **event,
    }
    line = json.dumps(envelope, ensure_ascii=False) + "\n"
    with open(events_path, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def emit_shape_asset(session: Path, brep_rel: str) -> int:
    """Append one placeholder `add` (kind:shape, occt-brep asset) for a brep.

    Offline driver for the occ-mesh-daemon path (plan §6). This stands in for
    what occdbg would emit from a breakpoint: a placeholder shape carrying a
    bbox (so the viewer draws a box immediately) plus an occt-brep asset
    reference the daemon meshes and upgrades to a real triangle mesh.

    Behaviour matches §4's placeholder add example. Append-only; never
    truncates events.ndjson. seq is scoped to this brep's source run_id.
    """
    brep_rel = brep_rel.lstrip("/")
    rel_path = Path(brep_rel)
    # run_id from a leading "run-NNNN/" segment, else run-0001.
    run_id = "run-0001"
    if rel_path.parts and RUN_RE.match(rel_path.parts[0]):
        run_id = rel_path.parts[0]
    entity_id = rel_path.stem  # e.g. run-0001/shape-7.brep -> "shape-7"

    (session / "assets").mkdir(parents=True, exist_ok=True)
    events_path = session / "events.ndjson"
    ensure_manifest(session)

    # seq: continue this run's sequence if it already has events, else start at 1.
    seq = 1
    if events_path.exists():
        highest = 0
        for raw in events_path.open(encoding="utf-8"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("run_id") == run_id and isinstance(ev.get("seq"), int):
                highest = max(highest, ev["seq"])
        seq = highest + 1

    add_event = {
        "op": "add",
        "id": entity_id,
        "group": "debug",
        "kind": "shape",
        "label": f"占位 {entity_id}",
        "geometry": {"bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}},
        "asset": {"format": "occt-brep", "path": brep_rel},
        "metadata": {"producer": "fake-session", "placeholder": True},
    }
    append_line(events_path, add_event, run_id, seq)
    print(f"[fake-session] session={session}")
    print(f"[fake-session] emit-shape-asset run_id={run_id} seq={seq} "
          f"id={entity_id} asset={brep_rel}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake OCC debug session producer (linkage slice C).")
    default_session = os.environ.get("OCC_DEBUG_SESSION", ".occ-debug/sessions/dev")
    parser.add_argument("--session", default=default_session, help="Session directory (default: $OCC_DEBUG_SESSION or .occ-debug/sessions/dev)")
    parser.add_argument("--interval", type=float, default=0.8, help="Seconds between appended events in stream mode (default: 0.8)")
    parser.add_argument("--once", action="store_true", help="Write all events immediately, no delay")
    parser.add_argument("--fresh", action="store_true", help="Force a brand-new session file (truncate); connected viewers must refresh")
    parser.add_argument("--emit-shape-asset", metavar="REL", default=None,
                        help="Append one placeholder shape+occt-brep `add` for REL (relative to assets/), then exit. For the occ-mesh-daemon offline test (plan §6).")
    args = parser.parse_args()

    session = Path(args.session)

    # Daemon-path offline driver: emit one placeholder add and exit. Leaves the
    # default fresh/reset streaming behaviour above completely untouched.
    if args.emit_shape_asset is not None:
        return emit_shape_asset(session, args.emit_shape_asset)

    (session / "assets").mkdir(parents=True, exist_ok=True)
    events_path = session / "events.ndjson"

    is_fresh = args.fresh or not events_path.exists() or events_path.stat().st_size == 0
    if args.fresh:
        events_path.write_text("", encoding="utf-8")
    ensure_manifest(session)

    if is_fresh:
        run_id = "run-0001"
        events = [*BASELINE_EVENTS, *DEBUG_EVENTS, RUN_END_EVENT]
        mode = "fresh"
    else:
        run_id = f"run-{scan_runs(events_path) + 1:04d}"
        # clear_scene wipes the previous run's debug objects (baseline is
        # protected and persists), then we re-emit the debug objects.
        events = [CLEAR_SCENE_EVENT, *DEBUG_EVENTS, RUN_END_EVENT]
        mode = "reset"

    print(f"[fake-session] session={session}")
    print(f"[fake-session] mode={mode}  run_id={run_id}  events={events_path}")

    for index, event in enumerate(events):
        seq = index + 1
        append_line(events_path, event, run_id, seq)
        label = event.get("label", event["op"])
        print(f"[fake-session] seq={seq} {event['op']:<11} {label}")
        if not args.once and index < len(events) - 1:
            time.sleep(args.interval)

    print(f"[fake-session] done: {len(events)} events ({mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# =====================================================================
# occ_capture — LLDB commands that emit LIVE OCCT geometry into a Print debug
# session, so a breakpoint inside ChFi3d / BRepFilletAPI can stream the actual
# fillet surfaces, spine and common points into the Print viewer in real time.
#
# This is the M3 capture last-mile. It reuses what already exists:
#   - BRepTools::Write(var, path) evaluated IN the inferior (same trick as the
#     existing `occ_save` command in lldb_occt_formatters.py),
#   - the Print event envelope (one flock-guarded line per event, risk N4),
#   - occ-mesh-daemon, which turns the written *.brep into a triangle mesh and
#     appends the `update`/`defect` events the viewer renders.
#
# Pipeline:  (lldb) occ_emit_shape Fd->ChangeSurf()   # a fillet face/surface
#   -> BRepTools::Write into <session>/assets/<run>/<id>.brep
#   -> append `add`(kind:shape, occt-brep asset)  ── occ-mesh-daemon ─► mesh
#   -> Print shows the placeholder box snap to the real surface, live.
#
# Load in LLDB (alongside the formatters):
#   (lldb) command script import scripts/occ_capture.py
# At a breakpoint:
#   (lldb) occ_emit_shape <shapeVar> [--id NAME] [--label TXT] [--group G]
#   (lldb) occ_emit_point <gp_Pnt var> [--id NAME] [--color #rrggbb]
#   (lldb) occ_emit_points <NCollection_Array1<gp_Pnt> var> [--id NAME]
#
# Session dir = $OCC_DEBUG_SESSION (default .occ-debug/sessions/dev). Start the
# producer side first:  scripts/occ-debug-start.sh start   (daemon + health),
# plus the Bridge + viewer (npm run dev) to watch it live.
# =====================================================================
import fcntl
import json
import os
import re
import shlex
import time
from pathlib import Path

SCHEMA_VERSION = "1.0"
RUN_RE = re.compile(r"^run-(\d+)$")

# One capture run_id + monotonic seq for this LLDB session, kept distinct from
# any run already in the file (so we never collide with occdbg/daemon seqs, V1).
_STATE = {"run_id": None, "seq": 0, "session_id": None}


def _session_dir() -> Path:
    return Path(os.environ.get("OCC_DEBUG_SESSION", ".occ-debug/sessions/dev"))


def _events_path(session: Path) -> Path:
    return session / "events.ndjson"


def _session_id(session: Path) -> str:
    if _STATE["session_id"]:
        return _STATE["session_id"]
    sid = "occ-lldb"
    manifest = session / "manifest.json"
    if manifest.exists():
        try:
            sid = json.loads(manifest.read_text(encoding="utf-8")).get("session_id", sid)
        except (json.JSONDecodeError, OSError):
            pass
    _STATE["session_id"] = sid
    return sid


def _run_id(session: Path) -> str:
    """Pick a fresh run-NNNN once per LLDB session (above any already present)."""
    if _STATE["run_id"] is None:
        highest = 0
        events = _events_path(session)
        if events.exists():
            for raw in events.open(encoding="utf-8"):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    match = RUN_RE.match(json.loads(raw).get("run_id", ""))
                except json.JSONDecodeError:
                    continue
                if match:
                    highest = max(highest, int(match.group(1)))
        _STATE["run_id"] = f"run-{highest + 1:04d}"
        _STATE["seq"] = 0
    return _STATE["run_id"]


def _append(session: Path, **fields) -> dict:
    """Append one complete Print event as a single flock-guarded line (N4)."""
    run_id = _run_id(session)
    _STATE["seq"] += 1
    event = {
        "schema_version": SCHEMA_VERSION,
        "session_id": _session_id(session),
        "run_id": run_id,
        "seq": _STATE["seq"],
        "timestamp_ns": time.time_ns(),
        **fields,
    }
    events = _events_path(session)
    events.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with open(events, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return event


# ---- option parsing --------------------------------------------------------
def _parse(command: str):
    """Split an LLDB command line into (positionals, {--flag: value})."""
    tokens = shlex.split(command.strip())
    pos, opts, i = [], {}, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            key = tok[2:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                opts[key] = tokens[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            pos.append(tok)
            i += 1
    return pos, opts


def _frame(exe_ctx, result):
    frame = exe_ctx.GetFrame()
    if not frame or not frame.IsValid():
        result.SetError("No valid frame — are you stopped at a breakpoint?")
        return None
    return frame


def _source_ref(frame):
    """{'file','line','function'} for the current stop, for the event's source."""
    try:
        line_entry = frame.GetLineEntry()
        fn = frame.GetFunctionName() or frame.GetDisplayFunctionName()
        spec = line_entry.GetFileSpec()
        return {
            "file": spec.GetFilename() or "",
            "line": int(line_entry.GetLine()) or 1,
            "function": fn or "",
        }
    except Exception:  # noqa: BLE001 — LLDB API surfaces vary; source is best-effort
        return None


def _eval_double(frame, expr):
    value = frame.EvaluateExpression(expr)
    if value.GetError().Fail():
        return None
    try:
        return float(value.GetValue())
    except (TypeError, ValueError):
        return None


def _read_pnt(frame, varname):
    """(x, y, z) of a gp_Pnt-like variable, via X()/Y()/Z() in the inferior."""
    coords = [_eval_double(frame, f"({varname}).{axis}()") for axis in ("X", "Y", "Z")]
    return None if any(c is None for c in coords) else coords


# ---- occ_emit_shape : TopoDS_Shape -> BREP asset -> daemon mesh ------------
def occ_emit_shape(debugger, command, exe_ctx, result, _internal_dict):
    """occ_emit_shape <shapeVar> [--id NAME] [--label TXT] [--group G]

    Write a TopoDS_Shape (face/shell/solid/compound) to the session's assets as
    BREP and emit a placeholder `shape` add; the running occ-mesh-daemon meshes
    it and the viewer swaps the placeholder box for the real surface.
    """
    pos, opts = _parse(command)
    if not pos:
        result.SetError("Usage: occ_emit_shape <shapeVar> [--id NAME] [--label TXT] [--group G]")
        return
    frame = _frame(exe_ctx, result)
    if frame is None:
        return

    varname = pos[0]
    session = _session_dir()
    run_id = _run_id(session)
    ent_id = opts.get("id") or _safe_id(varname, _STATE["seq"] + 1)
    rel = f"{run_id}/{ent_id}.brep"
    abspath = (session / "assets" / rel).resolve()
    abspath.parent.mkdir(parents=True, exist_ok=True)

    expr = f'BRepTools::Write({varname}, "{abspath}")'
    ret = frame.EvaluateExpression(expr)
    if ret.GetError().Fail():
        result.SetError(
            f"BRepTools::Write failed: {ret.GetError().GetCString()}\n"
            "If the symbol is missing: (lldb) expr #include <BRepTools.hxx>"
        )
        return

    fields = {
        "op": "add",
        "id": ent_id,
        "group": opts.get("group", "lldb/shapes"),
        "kind": "shape",
        "label": opts.get("label", f"{varname} @ breakpoint"),
        # Placeholder bbox; the daemon replaces it with the real meshed surface.
        "geometry": {"bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}},
        "asset": {"format": "occt-brep", "path": rel},
        "metadata": {"producer": "occ_capture", "var": varname},
    }
    source = _source_ref(frame)
    if source:
        fields["source"] = source
    _append(session, **fields)
    result.AppendMessage(f"[occ_capture] shape {ent_id} -> assets/{rel}  (daemon will mesh it)")


# ---- occ_emit_point : gp_Pnt -> Print point -------------------------------
def occ_emit_point(debugger, command, exe_ctx, result, _internal_dict):
    """occ_emit_point <gp_Pnt var> [--id NAME] [--color #rrggbb] [--label TXT]"""
    pos, opts = _parse(command)
    if not pos:
        result.SetError("Usage: occ_emit_point <gp_Pnt var> [--id NAME] [--color #rrggbb]")
        return
    frame = _frame(exe_ctx, result)
    if frame is None:
        return

    varname = pos[0]
    xyz = _read_pnt(frame, varname)
    if xyz is None:
        result.SetError(f"Could not read gp_Pnt from '{varname}' (X()/Y()/Z()).")
        return

    session = _session_dir()
    ent_id = opts.get("id") or _safe_id(varname, _STATE["seq"] + 1)
    fields = {
        "op": "add",
        "id": ent_id,
        "group": opts.get("group", "lldb/points"),
        "kind": "point",
        "label": opts.get("label", f"{varname} {tuple(round(v, 4) for v in xyz)}"),
        "geometry": {"position": xyz},
        "style": {"color": opts.get("color", "#efb45f"), "size": 0.3},
        "metadata": {"producer": "occ_capture", "var": varname},
    }
    source = _source_ref(frame)
    if source:
        fields["source"] = source
    _append(session, **fields)
    result.AppendMessage(f"[occ_capture] point {ent_id} = {xyz}")


# ---- occ_emit_points : NCollection_Array1<gp_Pnt> -> point_set ------------
def occ_emit_points(debugger, command, exe_ctx, result, _internal_dict):
    """occ_emit_points <Array1<gp_Pnt> var> [--id NAME] [--color #rrggbb]

    Reads Lower()..Upper() and Value(i).{X,Y,Z}() in the inferior.
    """
    pos, opts = _parse(command)
    if not pos:
        result.SetError("Usage: occ_emit_points <Array1<gp_Pnt> var> [--id NAME]")
        return
    frame = _frame(exe_ctx, result)
    if frame is None:
        return

    varname = pos[0]
    lo = _eval_double(frame, f"({varname}).Lower()")
    hi = _eval_double(frame, f"({varname}).Upper()")
    if lo is None or hi is None:
        result.SetError(f"Could not read Lower()/Upper() of '{varname}'.")
        return
    positions = []
    for i in range(int(lo), int(hi) + 1):
        xyz = _read_pnt(frame, f"({varname}).Value({i})")
        if xyz is not None:
            positions.append(xyz)
    if not positions:
        result.SetError(f"No readable gp_Pnt values in '{varname}'.")
        return

    session = _session_dir()
    ent_id = opts.get("id") or _safe_id(varname, _STATE["seq"] + 1)
    fields = {
        "op": "add",
        "id": ent_id,
        "group": opts.get("group", "lldb/points"),
        "kind": "point_set",
        "label": opts.get("label", f"{varname} ×{len(positions)}"),
        "geometry": {"positions": positions},
        "style": {"color": opts.get("color", "#9ac6b6"), "size": 6},
        "metadata": {"producer": "occ_capture", "var": varname},
    }
    source = _source_ref(frame)
    if source:
        fields["source"] = source
    _append(session, **fields)
    result.AppendMessage(f"[occ_capture] point_set {ent_id} = {len(positions)} pts")


# ---- occ_emit_surface : in-progress Geom_Surface -> face -> mesh ----------
def occ_emit_surface(debugger, command, exe_ctx, result, _internal_dict):
    """occ_emit_surface <Geom_Surface var> [--tol T] [--bounds umin,umax,vmin,vmax] [--id NAME] [--label TXT]

    Wrap an IN-PROGRESS parametric surface (a Handle(Geom_Surface) — e.g. a
    fillet surface mid-ChFi3d, before it becomes a TopoDS_Face) into a face IN
    the inferior via BRepBuilderAPI_MakeFace, write it to BREP, and emit it. The
    daemon meshes it like any other shape, so you can see a fillet face that does
    not yet exist as topology. Bounded surfaces (B-spline) work with just --tol;
    for an unbounded one (plane/cylinder) pass --bounds umin,umax,vmin,vmax.
    """
    pos, opts = _parse(command)
    if not pos:
        result.SetError("Usage: occ_emit_surface <Geom_Surface var> [--tol T] [--bounds umin,umax,vmin,vmax]")
        return
    frame = _frame(exe_ctx, result)
    if frame is None:
        return

    varname = pos[0]
    tol = opts.get("tol", "1e-6")
    bounds = opts.get("bounds")
    if bounds and bounds is not True:
        try:
            u0, u1, v0, v1 = (s.strip() for s in str(bounds).split(","))
        except ValueError:
            result.SetError("--bounds must be umin,umax,vmin,vmax")
            return
        face_expr = f"BRepBuilderAPI_MakeFace({varname}, {u0}, {u1}, {v0}, {v1}, {tol}).Face()"
    else:
        face_expr = f"BRepBuilderAPI_MakeFace({varname}, {tol}).Face()"

    session = _session_dir()
    run_id = _run_id(session)
    ent_id = opts.get("id") or _safe_id(varname, _STATE["seq"] + 1)
    rel = f"{run_id}/{ent_id.replace('/', '_')}.brep"
    abspath = (session / "assets" / rel).resolve()
    abspath.parent.mkdir(parents=True, exist_ok=True)

    expr = f'BRepTools::Write({face_expr}, "{abspath}")'
    ret = frame.EvaluateExpression(expr)
    if ret.GetError().Fail():
        result.SetError(
            f"MakeFace/Write failed: {ret.GetError().GetCString()}\n"
            "Need: (lldb) expr #include <BRepBuilderAPI_MakeFace.hxx>\n"
            "If the surface is unbounded (plane/cylinder), pass --bounds umin,umax,vmin,vmax."
        )
        return

    fields = {
        "op": "add",
        "id": ent_id,
        "group": opts.get("group", "lldb/surfaces"),
        "kind": "shape",
        "label": opts.get("label", f"{varname} (surface→face)"),
        "geometry": {"bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}},
        "asset": {"format": "occt-brep", "path": rel},
        "style": {"color": opts.get("color", "#e0a34e"), "opacity": 0.6},
        "metadata": {"producer": "occ_capture", "var": varname, "from": "surface"},
    }
    source = _source_ref(frame)
    if source:
        fields["source"] = source
    _append(session, **fields)
    result.AppendMessage(f"[occ_capture] surface→face {ent_id} -> assets/{rel}  (daemon will mesh it)")


def _safe_id(varname: str, seq: int) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "-", varname).strip("-") or "var"
    return f"lldb/{base}-{seq}"


def __lldb_init_module(debugger, _internal_dict):
    module = Path(__file__).stem  # "occ_capture"
    for name in ("occ_emit_shape", "occ_emit_surface", "occ_emit_point", "occ_emit_points"):
        debugger.HandleCommand(f"command script add -f {module}.{name} {name}")
    print("[occ_capture] commands: occ_emit_shape / occ_emit_surface / occ_emit_point / occ_emit_points")

"""LLDB summaries and synthetic children for common OCCT value types."""

import json
import struct

import lldb


_ORIENTATIONS = {
    0: "FORWARD",
    1: "REVERSED",
    2: "INTERNAL",
    3: "EXTERNAL",
}

_SHAPE_TYPES = (
    ("CompSolid", "COMPSOLID"),
    ("Compound", "COMPOUND"),
    ("Vertex", "VERTEX"),
    ("Edge", "EDGE"),
    ("Wire", "WIRE"),
    ("Face", "FACE"),
    ("Shell", "SHELL"),
    ("Solid", "SOLID"),
)


def _raw(value):
    raw = value.GetNonSyntheticValue()
    return raw if raw.IsValid() else value


def _member(value, name, depth=0):
    """Find a field through base classes and small wrapper objects."""
    if not value.IsValid() or depth > 5:
        return lldb.SBValue()

    value = _raw(value)
    direct = value.GetChildMemberWithName(name)
    if direct.IsValid():
        return direct

    for index in range(value.GetNumChildren()):
        child = value.GetChildAtIndex(index)
        found = _member(child, name, depth + 1)
        if found.IsValid():
            return found
    return lldb.SBValue()


def _integer(value, depth=0):
    if not value.IsValid() or depth > 5:
        return None

    text = value.GetValue()
    if text:
        for number, name in _ORIENTATIONS.items():
            if text == name or text.endswith("_" + name):
                return number
        try:
            return int(text, 0)
        except ValueError:
            pass

        failure = -(1 << 63)
        numeric = value.GetValueAsSigned(failure)
        if numeric != failure:
            return numeric

    value = _raw(value)
    for index in range(value.GetNumChildren()):
        result = _integer(value.GetChildAtIndex(index), depth + 1)
        if result is not None:
            return result
    return None


def _real(value):
    if not value.IsValid():
        return None
    text = value.GetValue()
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pointer(value):
    return value.GetValueAsUnsigned(0) if value.IsValid() else 0


def _dynamic_pointee_name(pointer):
    if not pointer.IsValid() or _pointer(pointer) == 0:
        return ""
    dynamic = pointer.GetDynamicValue(lldb.eDynamicDontRunTarget)
    type_name = dynamic.GetTypeName() if dynamic.IsValid() else pointer.GetTypeName()
    return (type_name or "").rstrip(" *")


def _shape_kind(type_name):
    for token, label in _SHAPE_TYPES:
        if token in type_name:
            return label
    return "SHAPE"


def _escape(text, limit=160):
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return text if len(text) <= limit else text[:limit] + "..."


def handle_summary(value, _internal_dict):
    entity = _member(value, "entity")
    address = _pointer(entity)
    if address == 0:
        return "NULL"

    dynamic_name = _dynamic_pointee_name(entity) or "Standard_Transient"
    ref_count = _integer(_member(entity.Dereference(), "myRefCount_"))
    refs = "?" if ref_count is None else str(ref_count)
    return f"{dynamic_name} @ 0x{address:x}, refs={refs}"


def shape_summary(value, _internal_dict):
    tshape = _member(value, "myTShape")
    entity = _member(tshape, "entity")
    address = _pointer(entity)
    orientation_value = _integer(_member(value, "myOrient"))
    orientation = _ORIENTATIONS.get(orientation_value, f"ORIENT({orientation_value})")

    if address == 0:
        return f"NULL {orientation}"

    dynamic = entity.GetDynamicValue(lldb.eDynamicDontRunTarget)
    dynamic_name = _dynamic_pointee_name(entity)
    shape_kind = _shape_kind(dynamic_name)
    tshape_object = dynamic.Dereference() if dynamic.IsValid() else entity.Dereference()
    child_count = _integer(_member(_member(tshape_object, "myShapes"), "myLength"))
    flags = _integer(_member(tshape_object, "myFlags"))

    location_node = _member(_member(_member(value, "myLocation"), "myItems"), "myNode")
    location_entity = _member(location_node, "entity")
    location = "identity" if _pointer(location_entity) == 0 else "located"

    children = "?" if child_count is None else str(child_count)
    flags_text = "?" if flags is None else f"0x{flags:x}"
    return (
        f"{shape_kind} {orientation}, children={children}, {location}, "
        f"tshape=0x{address:x}, flags={flags_text}"
    )


def tshape_summary(value, _internal_dict):
    dynamic_name = value.GetTypeName() or "TopoDS_TShape"
    child_count = _integer(_member(_member(value, "myShapes"), "myLength"))
    flags = _integer(_member(value, "myFlags"))
    children = "?" if child_count is None else str(child_count)
    flags_text = "?" if flags is None else f"0x{flags:x}"
    return f"{_shape_kind(dynamic_name)}, children={children}, flags={flags_text}"


def coordinate_summary(value, _internal_dict):
    raw = _raw(value)
    coord = _member(raw, "coord")
    source = coord if coord.IsValid() else raw
    names = ("x", "y", "z")
    components = []
    for name in names:
        number = _real(_member(source, name))
        if number is not None:
            components.append(f"{name}={number:.9g}")
    return "(" + ", ".join(components) + ")" if components else "<coordinates unavailable>"


class CoordinateSyntheticProvider:
    """Expose x/y/z directly instead of under the private coord field."""

    def __init__(self, value, _internal_dict):
        self.value = value
        self.children = []
        self.update()

    def update(self):
        raw = _raw(self.value)
        coord = _member(raw, "coord")
        source = coord if coord.IsValid() else raw
        self.children = []
        for name in ("x", "y", "z"):
            child = _member(source, name)
            if child.IsValid():
                self.children.append(child)
        return False

    def num_children(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index] if 0 <= index < len(self.children) else None

    def get_child_index(self, name):
        for index, child in enumerate(self.children):
            if child.GetName() == name:
                return index
        return -1

    def has_children(self):
        return bool(self.children)


def ascii_string_summary(value, _internal_dict):
    length = _integer(_member(value, "mylength"))
    pointer = _pointer(_member(value, "mystring"))
    if length is None or pointer == 0:
        return '""' if length == 0 else "NULL"

    error = lldb.SBError()
    data = value.GetProcess().ReadMemory(pointer, min(length, 4096), error)
    if not error.Success():
        return f"length={length}, <unreadable>"
    text = data.decode("utf-8", errors="replace")
    return f'length={length}, "{_escape(text)}"'


def extended_string_summary(value, _internal_dict):
    length = _integer(_member(value, "mylength"))
    pointer = _pointer(_member(value, "mystring"))
    if length is None or pointer == 0:
        return 'u""' if length == 0 else "NULL"

    error = lldb.SBError()
    data = value.GetProcess().ReadMemory(pointer, min(length, 2048) * 2, error)
    if not error.Success():
        return f"length={length}, <unreadable>"
    text = data.decode("utf-16-le", errors="replace")
    return f'length={length}, u"{_escape(text)}"'


def collection_summary(value, _internal_dict):
    for field in ("myLength", "mySize", "myExtent"):
        size = _integer(_member(value, field))
        if size is not None:
            return f"size={size}"

    lower = _integer(_member(value, "myLowerBound"))
    upper = _integer(_member(value, "myUpperBound"))
    if lower is not None and upper is not None:
        return f"size={max(0, upper - lower + 1)}, bounds=[{lower}..{upper}]"
    return "size=?"


def orientation_summary(value, _internal_dict):
    number = _integer(value)
    return _ORIENTATIONS.get(number, f"UNKNOWN({number})")


# =============================================================================
# Debug Visualizer emitters
# =============================================================================
# Use these LLDB commands in the Debug Visualizer watch box.
# (script/print output goes to the debug console, not back to Debug Visualizer;
#  result.AppendMessage() is the only reliable DAP-response path.)
#
#   Vertex point cloud (TopoDS_Shape):
#     occ_viz_shape_pts myShape
#
#   Topology DAG (TopoDS_Shape):
#     occ_viz_topo myShape
#
#   BSpline poles / control polygon (TColgp_Array1OfPnt):
#     occ_viz_pts thePoles
#
#   ChFiDS_Spine polyline (ChFiDS_Spine or handle<ChFiDS_Spine>):
#     occ_viz_spine mySpine
#
#   A point on a curve, both in one graph (gp_Pnt + any curve):
#     occ_viz_pt_curve pt cv
#
#   Any number of points and/or curves overlaid in one graph:
#     occ_viz_geom pt1 pt2 cv1 cv2
#
#   Save shape to BREP for external viewing:
#     occ_save myShape [/tmp/out.brep]
# =============================================================================


def _read_xyz(val):
    """Return (x, y, z) from gp_Pnt / gp_XYZ / gp_Vec / gp_Dir, or None."""
    coord = _member(val, "coord")
    src = coord if coord.IsValid() else val
    x = _real(_member(src, "x"))
    y = _real(_member(src, "y"))
    z = _real(_member(src, "z"))
    return (x, y, z) if None not in (x, y, z) else None


def _read_xy(val):
    """Return (x, y) from gp_Pnt2d / gp_XY / gp_Vec2d / gp_Dir2d, or None."""
    coord = _member(val, "coord")
    src = coord if coord.IsValid() else val
    x = _real(_member(src, "x"))
    y = _real(_member(src, "y"))
    return (x, y) if None not in (x, y) else None


def _read_point_any(val):
    """Return (x, y, z) from a 3D or 2D point value (z=0 for 2D), or None."""
    xyz = _read_xyz(val)
    if xyz is not None:
        return xyz
    xy = _read_xy(val)
    if xy is not None:
        return (xy[0], xy[1], 0.0)
    return None


def _list_walk(list_val, item_typename, max_items=500):
    """Yield SBValue items from an NCollection_List<item_typename>.

    NCollection_List stores a singly-linked list of ListNode objects.
    ListNode layout: [myNext* (ptr_size bytes)] [Value (sizeof T)].
    This matches NCollection_ListNode (myNext) + the derived Value field.
    """
    first_ptr = _member(list_val, "myFirst")
    if not first_ptr.IsValid():
        return
    node_addr = _pointer(first_ptr)
    if node_addr == 0:
        return

    target = list_val.GetTarget()
    item_type = target.FindFirstType(item_typename)
    process = target.GetProcess()
    ptr_size = target.GetAddressByteSize()
    ptr_fmt = "<Q" if ptr_size == 8 else "<I"
    count = 0

    while node_addr != 0 and count < max_items:
        value_addr = node_addr + ptr_size
        if item_type.IsValid():
            item = target.CreateValueFromAddress(
                f"[{count}]",
                lldb.SBAddress(value_addr, target),
                item_type,
            )
            yield item
        else:
            yield lldb.SBValue()

        err = lldb.SBError()
        raw = process.ReadMemory(node_addr, ptr_size, err)
        if not err.Success() or len(raw) < ptr_size:
            break
        node_addr = struct.unpack(ptr_fmt, raw)[0]
        count += 1


def _sequence_walk(seq_val, item_typename, max_items=200):
    """Yield SBValue items from NCollection_Sequence<item_typename>.

    NCollection_Sequence::Node (64-bit):
      [myNext* 8 bytes] [myPrev* 8 bytes] [myValue sizeof(T)]
    Follows the myNext chain starting at myFirst.
    """
    first_ptr = _member(seq_val, "myFirstItem")
    if not first_ptr.IsValid():
        return
    node_addr = _pointer(first_ptr)
    if node_addr == 0:
        return

    target = seq_val.GetTarget()
    item_type = target.FindFirstType(item_typename)
    process = target.GetProcess()
    ptr_size = target.GetAddressByteSize()
    ptr_fmt = "<Q" if ptr_size == 8 else "<I"
    count = 0

    while node_addr != 0 and count < max_items:
        value_addr = node_addr + 2 * ptr_size  # skip myNext + myPrevious
        if item_type.IsValid():
            item = target.CreateValueFromAddress(
                f"[{count}]",
                lldb.SBAddress(value_addr, target),
                item_type,
            )
            yield item
        else:
            yield lldb.SBValue()

        err = lldb.SBError()
        raw = process.ReadMemory(node_addr, ptr_size, err)
        if not err.Success() or len(raw) < ptr_size:
            break
        node_addr = struct.unpack(ptr_fmt, raw)[0]
        count += 1


# ---- occ_topo: topology DAG -----------------------------------------------

def _collect_topo(shape_val, nodes, edges, visited, parent_id=None, depth=0):
    if depth > 12 or len(nodes) >= 200:
        return

    tshape_handle = _member(shape_val, "myTShape")
    entity_ptr = _member(tshape_handle, "entity")
    tshape_addr = _pointer(entity_ptr)
    if tshape_addr == 0:
        return

    node_id = f"0x{tshape_addr:x}"
    orient_val = _integer(_member(shape_val, "myOrient"))
    orient = _ORIENTATIONS.get(orient_val, "?")

    if parent_id is not None:
        edges.append({"from": parent_id, "to": node_id, "label": orient})

    if tshape_addr in visited:
        return  # already expanded; edge above is still valid (shared TShape)
    visited.add(tshape_addr)

    dyn_name = _dynamic_pointee_name(entity_ptr)
    kind = _shape_kind(dyn_name)
    nodes.append({"id": node_id, "label": f"{kind}\n@{tshape_addr:x}"})

    dynamic = entity_ptr.GetDynamicValue(lldb.eDynamicDontRunTarget)
    tshape_obj = dynamic.Dereference() if dynamic.IsValid() else entity_ptr.Dereference()
    my_shapes = _member(tshape_obj, "myShapes")
    if not my_shapes.IsValid():
        return

    for child_val in _list_walk(my_shapes, "TopoDS_Shape"):
        if child_val.IsValid():
            _collect_topo(child_val, nodes, edges, visited, node_id, depth + 1)


def occ_topo(value):
    """Return Debug Visualizer Graph JSON for a TopoDS_Shape topology DAG.

    Reads topology purely from memory (no target execution).
    Shared TShapes appear as a single node with multiple incoming edges.
    Capped at 200 nodes to keep the graph renderable.
    """
    nodes, edges = [], []
    _collect_topo(value, nodes, edges, set())
    return json.dumps({"kind": {"graph": True}, "nodes": nodes, "edges": edges})


# ---- occ_shape_pts: vertex point cloud ------------------------------------

def _collect_vertices(shape_val, pts, visited, depth=0):
    if depth > 15:
        return

    tshape_handle = _member(shape_val, "myTShape")
    entity_ptr = _member(tshape_handle, "entity")
    tshape_addr = _pointer(entity_ptr)
    if tshape_addr == 0 or tshape_addr in visited:
        return
    visited.add(tshape_addr)

    dyn_name = _dynamic_pointee_name(entity_ptr)
    dynamic = entity_ptr.GetDynamicValue(lldb.eDynamicDontRunTarget)
    tshape_obj = dynamic.Dereference() if dynamic.IsValid() else entity_ptr.Dereference()

    if "Vertex" in dyn_name:
        # BRep_TVertex stores gp_Pnt myPnt directly
        xyz = _read_xyz(_member(tshape_obj, "myPnt"))
        if xyz:
            pts.append(xyz)
        return

    my_shapes = _member(tshape_obj, "myShapes")
    if not my_shapes.IsValid():
        return
    for child_val in _list_walk(my_shapes, "TopoDS_Shape"):
        if child_val.IsValid():
            _collect_vertices(child_val, pts, visited, depth + 1)


def occ_shape_pts(value):
    """Return Debug Visualizer Plotly scatter3d JSON for all vertices of a TopoDS_Shape.

    Walks the full shape tree in memory; no target execution needed.
    Each point is labelled with its index and XYZ coordinates.
    """
    pts = []
    _collect_vertices(value, pts, set())
    if not pts:
        return json.dumps({"kind": {"text": True}, "text": "occ_shape_pts: no vertices found"})

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    labels = [f"V{i}<br>({x:.5g},{y:.5g},{z:.5g})" for i, (x, y, z) in enumerate(pts)]

    return json.dumps({
        "kind": {"plotly": True},
        "data": [{
            "type": "scatter3d",
            # Debug Visualizer's plotly serializer only accepts this exact
            # ordering ("text+markers", not "markers+text"); a wrong order
            # silently fails schema validation -> "No Visualization Available".
            "mode": "text+markers",
            "x": xs,
            "y": ys,
            "z": zs,
            "text": labels,
            "marker": {"size": 5, "color": "steelblue", "opacity": 0.85},
        }],
    })


# ---- occ_pts: TColgp_Array1OfPnt (BSpline poles, knots, etc.) -------------

def occ_pts(value):
    """Return Debug Visualizer Plotly scatter3d JSON for a TColgp_Array1OfPnt.

    Also draws the control polygon as a line connecting the points in order.
    Works for any NCollection_Array1<gp_Pnt>: poles, spine samples, etc.
    Reads raw memory (3 doubles per point) — no target execution.
    """
    lower = _integer(_member(value, "myLowerBound"))
    upper = _integer(_member(value, "myUpperBound"))
    if lower is None or upper is None:
        return json.dumps({"kind": {"text": True}, "text": "occ_pts: not an Array1OfPnt"})

    count = max(0, upper - lower + 1)
    if count == 0:
        return json.dumps({"kind": {"text": True}, "text": "occ_pts: empty array"})

    # OCCT 7.x NCollection_Array1 uses myBegin; older releases used myData
    data_ptr_val = _member(value, "myBegin")
    if not data_ptr_val.IsValid() or _pointer(data_ptr_val) == 0:
        data_ptr_val = _member(value, "myData")

    base_addr = _pointer(data_ptr_val)
    if base_addr == 0:
        return json.dumps({"kind": {"text": True}, "text": "occ_pts: null data pointer"})

    target = value.GetTarget()
    pnt_type = target.FindFirstType("gp_Pnt")
    pnt_size = pnt_type.GetByteSize() if pnt_type.IsValid() else 24  # 3 × double
    process = target.GetProcess()

    xs, ys, zs, labels = [], [], [], []
    for i in range(min(count, 500)):
        addr = base_addr + i * pnt_size
        err = lldb.SBError()
        raw = process.ReadMemory(addr, 24, err)
        if not err.Success() or len(raw) < 24:
            break
        x, y, z = struct.unpack_from("<ddd", raw)
        xs.append(x)
        ys.append(y)
        zs.append(z)
        labels.append(f"[{lower + i}]<br>({x:.5g},{y:.5g},{z:.5g})")

    if not xs:
        return json.dumps({"kind": {"text": True}, "text": "occ_pts: could not read points"})

    return json.dumps({
        "kind": {"plotly": True},
        "data": [{
            "type": "scatter3d",
            # See note in occ_shape_pts: order must match the serializer literal
            # ("lines+markers", not "markers+lines").
            "mode": "lines+markers",
            "x": xs,
            "y": ys,
            "z": zs,
            "text": labels,
            "marker": {"size": 4, "color": "orange"},
            "line": {"width": 2, "color": "orange"},
        }],
    })


# ---- occ_spine: ChFiDS_Spine polyline -------------------------------------

def occ_spine(value):
    """Return Debug Visualizer Plotly scatter3d JSON for a ChFiDS_Spine.

    Accepts ChFiDS_Spine or opencascade::handle<ChFiDS_Spine>.
    Walks the internal spine sequence (TopTools_SequenceOfShape) in memory;
    no target execution needed.  Collects each edge's endpoint vertices in
    sequence order so the rendered polyline traces the actual spine path.
    """
    # Unwrap opencascade::handle<ChFiDS_Spine> if needed
    type_name = value.GetTypeName() or ""
    if "handle" in type_name or "Handle" in type_name:
        entity = _member(value, "entity")
        if not entity.IsValid() or _pointer(entity) == 0:
            return json.dumps({"kind": {"text": True}, "text": "occ_spine: null handle"})
        value = entity.Dereference()

    spine_seq = _member(value, "spine")
    if not spine_seq.IsValid():
        return json.dumps({
            "kind": {"text": True},
            "text": "occ_spine: no 'spine' member — is this a ChFiDS_Spine?",
        })

    pts = []
    visited = set()
    found_edges = 0
    for edge_val in _sequence_walk(spine_seq, "TopoDS_Shape"):
        if edge_val.IsValid():
            found_edges += 1
            _collect_vertices(edge_val, pts, visited)

    if not pts:
        msg = (
            f"occ_spine: no vertices found (walked {found_edges} edges)"
            if found_edges
            else "occ_spine: spine sequence empty or unreadable"
        )
        return json.dumps({"kind": {"text": True}, "text": msg})

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    labels = [f"V{i}<br>({x:.5g},{y:.5g},{z:.5g})" for i, (x, y, z) in enumerate(pts)]

    return json.dumps({
        "kind": {"plotly": True},
        "data": [{
            "type": "scatter3d",
            "mode": "lines+markers",
            "x": xs,
            "y": ys,
            "z": zs,
            "text": labels,
            "marker": {"size": 4, "color": "crimson"},
            "line": {"width": 3, "color": "crimson"},
        }],
        "layout": {"title": "ChFiDS_Spine"},
    })


# ---- occ_pt_curve: a point overlaid on a sampled curve --------------------
# Unlike the pure-memory emitters above, a general curve (Geom_Curve handle,
# Adaptor3d_Curve, BSpline, ...) cannot be sampled from raw memory, so this
# evaluates cv.Value(t) in the target.  Value() is const -> no side effects,
# same target-execution approach occ_save already relies on.


def _eval_real(frame, expr):
    res = frame.EvaluateExpression(expr)
    if not res.GetError().Success():
        return None
    return _real(res)


def _curve_accessor(frame, cv_name):
    """Detect the member-call separator and parameter range of a curve var.

    Handles (Geom_Curve, ...) are called with '->'; value/adaptor curves
    (BRepAdaptor_Curve, GeomAdaptor_Curve, ...) with '.'.  Returns
    (sep, first, last) or (None, None, None) if neither form responds.
    """
    for sep in (".", "->"):
        first = _eval_real(frame, f"{cv_name}{sep}FirstParameter()")
        if first is None:
            continue
        last = _eval_real(frame, f"{cv_name}{sep}LastParameter()")
        if last is not None:
            return sep, first, last
    return None, None, None


# Distinct, color-blind-friendly-ish palette cycled across traces so each
# point/curve is visually separable in the combined graph.
_DV_COLORS = [
    "crimson", "steelblue", "seagreen", "darkorange",
    "mediumpurple", "teal", "goldenrod", "deeppink",
]


def _point_trace(frame, name, color):
    """Build a single-marker scatter3d trace for a point var, or None.

    Reads gp_Pnt/gp_Pnt2d from memory, falling back to a target evaluation.
    """
    val = frame.FindVariable(name)
    xyz = _read_point_any(val) if val.IsValid() else None
    if xyz is None:
        res = frame.EvaluateExpression(name)
        if res.GetError().Success():
            xyz = _read_point_any(res)
    if xyz is None:
        return None
    x, y, z = xyz
    return {
        "type": "scatter3d",
        "mode": "text+markers",
        "x": [x],
        "y": [y],
        "z": [z],
        "text": [f"{name}<br>({x:.5g},{y:.5g},{z:.5g})"],
        "name": name,
        "marker": {"size": 8, "color": color, "symbol": "diamond"},
    }


def _curve_trace(frame, name, color, samples=40):
    """Build a polyline scatter3d trace for a curve var, or None.

    Samples name.Value(t) over [FirstParameter, LastParameter] in the target;
    auto-detects '.' vs '->' and 3D vs 2D.  Value() is const -> no side effects.
    """
    sep, first, last = _curve_accessor(frame, name)
    if sep is None:
        return None

    xs, ys, zs, labels = [], [], [], []
    span = last - first
    for i in range(samples + 1):
        t = first + span * i / samples
        res = frame.EvaluateExpression(f"{name}{sep}Value({t!r})")
        if not res.GetError().Success():
            continue
        c = _read_point_any(res)
        if c is None:
            continue
        xs.append(c[0])
        ys.append(c[1])
        zs.append(c[2])
        labels.append(f"t={t:.5g}<br>({c[0]:.5g},{c[1]:.5g},{c[2]:.5g})")

    if not xs:
        return None
    return {
        "type": "scatter3d",
        # mode strings must match the serializer literals exactly;
        # see the note in occ_shape_pts / occ_pts.
        "mode": "lines+markers",
        "x": xs,
        "y": ys,
        "z": zs,
        "text": labels,
        "name": name,
        "marker": {"size": 2, "color": color},
        "line": {"width": 3, "color": color},
    }


def occ_geom(frame, names, samples=40):
    """Return Debug Visualizer Plotly JSON overlaying any mix of points/curves.

    `names` is a list of INDEPENDENT variable names (no relationship assumed).
    Each is auto-classified: a value exposing coord x/y[/z] is drawn as a
    marker; anything answering FirstParameter/Value(t) is sampled as a curve.
    Each trace gets its own color so two points and two curves stay separable.
    """
    traces, skipped = [], []
    for idx, name in enumerate(names):
        color = _DV_COLORS[idx % len(_DV_COLORS)]
        trace = _point_trace(frame, name, color) or _curve_trace(frame, name, color, samples)
        if trace is None:
            skipped.append(name)
        else:
            traces.append(trace)

    if not traces:
        return json.dumps({
            "kind": {"text": True},
            "text": (
                "occ_geom: none of "
                f"{', '.join(names)} read as a point (gp_Pnt) or curve "
                "(FirstParameter/Value via '.' or '->')"
            ),
        })

    title = " & ".join(names)
    if skipped:
        title += f"  (skipped: {', '.join(skipped)})"
    return json.dumps({
        "kind": {"plotly": True},
        "data": traces,
        "layout": {"title": title},
    })


def occ_pt_curve(frame, pt_name, cv_name, samples=40):
    """Back-compat shim: a point and a curve in one graph. See occ_geom."""
    return occ_geom(frame, [pt_name, cv_name], samples)


# ---- occ_save LLDB command ------------------------------------------------

def occ_save_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Save a TopoDS_Shape variable to a .brep file via BRepTools::Write.

    Usage (LLDB console):
      occ_save <varname> [output_path]

    Default output path: /tmp/occ_<varname>.brep
    Open the result with FreeCAD, CAD Assistant, or DRAW Harness.
    """
    args = command.strip().split()
    if not args:
        result.SetError("Usage: occ_save <varname> [path]")
        return

    varname = args[0]
    path = args[1] if len(args) > 1 else f"/tmp/occ_{varname}.brep"

    frame = exe_ctx.GetFrame()
    if not frame or not frame.IsValid():
        result.SetError("No valid frame — are you stopped at a breakpoint?")
        return

    expr = f'BRepTools::Write({varname}, "{path}")'
    ret = frame.EvaluateExpression(expr)
    if ret.GetError().Fail():
        result.SetError(
            f"BRepTools::Write failed: {ret.GetError().GetCString()}\n"
            "If the symbol is missing, try: expr #include <BRepTools.hxx>"
        )
        return

    result.AppendMessage(f"Saved to {path}")


# ---- LLDB commands for Debug Visualizer -----------------------------------
# script/print output goes to the VS Code debug console, NOT back to Debug
# Visualizer via a two-channel approach:
#   1. Run an LLDB command in the debug console to write JSON to a temp file.
#   2. Debug Visualizer reads that file via a watch expression whose return
#      value goes into DAP EvaluateResponse.result, which is the only channel
#      Debug Visualizer actually reads.  AppendMessage/print go to the VS Code
#      output channel instead, which is why those approaches fail.
#      The template uses CodeLLDB's native evaluator (/nat prefix) returning a
#      pointer to an INCOMPLETE struct (struct __dv_payload*).  Debug Visualizer
#      graphs the value's children whenever variablesReference != 0 (ignoring the
#      JSON), so the value must have no children: an incomplete type cannot be
#      dereferenced -> no children -> variablesReference == 0, and
#      dv_payload_summary surfaces the JSON as its summary.  Do NOT use /py or a
#      char*/char[N]: those are expandable and get graphed instead.  See
#      settings.json expressionTemplate and docs/occt-debugging.md.
#
# Workflow:
#   a) In LLDB console (VS Code debug console), run ONE of:
#        occ_viz_shape_pts Vtx
#        occ_viz_topo myShape
#        occ_viz_pts thePoles
#      → writes /tmp/occ_dv_<varname>.json
#   b) In Debug Visualizer watch box, type the variable name, e.g.: Vtx
#      The expressionTemplate in settings.json wraps it into a
#      /nat (struct __dv_payload*) fread call that reads /tmp/occ_dv_Vtx.json.
#   c) Debug Visualizer auto-refreshes on each step (re-reads the file).
#      Re-run the console command whenever you want to update the data.

_OCC_DV_DIR = "/tmp"


def _viz_cmd(fn, debugger, command, exe_ctx, result, _internal_dict):
    varname = command.strip()
    if not varname:
        result.SetError("Usage: occ_viz_* <varname>")
        return
    frame = exe_ctx.GetFrame()
    if not frame or not frame.IsValid():
        result.SetError("No valid frame — stopped at a breakpoint?")
        return
    val = frame.FindVariable(varname)
    try:
        output = fn(val)
    except Exception as exc:
        output = json.dumps({"kind": {"text": True}, "text": f"Error: {exc}"})

    path = f"{_OCC_DV_DIR}/occ_dv_{varname}.json"
    try:
        with open(path, "w") as fp:
            fp.write(output)
        result.AppendMessage(f"Written {path} — type '{varname}' in Debug Visualizer")
    except Exception as exc:
        result.AppendMessage(f"Could not write {path}: {exc}")


def occ_viz_shape_pts_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Debug Visualizer: 3D vertex point cloud of a TopoDS_Shape.

    Usage (Debug Visualizer watch box):  occ_viz_shape_pts <varname>
    """
    _viz_cmd(occ_shape_pts, debugger, command, exe_ctx, result, _internal_dict)


def occ_viz_topo_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Debug Visualizer: topology DAG of a TopoDS_Shape.

    Usage (Debug Visualizer watch box):  occ_viz_topo <varname>
    """
    _viz_cmd(occ_topo, debugger, command, exe_ctx, result, _internal_dict)


def occ_viz_pts_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Debug Visualizer: BSpline poles / control polygon from TColgp_Array1OfPnt.

    Usage (Debug Visualizer watch box):  occ_viz_pts <varname>
    """
    _viz_cmd(occ_pts, debugger, command, exe_ctx, result, _internal_dict)


def occ_viz_spine_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Debug Visualizer: ChFiDS_Spine polyline.

    Usage (debug console):  occ_viz_spine <varname>
    <varname> may be ChFiDS_Spine or opencascade::handle<ChFiDS_Spine>.
    Renders the spine edge vertices as a connected crimson polyline.
    """
    _viz_cmd(occ_spine, debugger, command, exe_ctx, result, _internal_dict)


def occ_viz_geom_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Debug Visualizer: overlay any number of points and curves in one graph.

    Usage (debug console):  occ_viz_geom <var1> <var2> [<var3> ...]
    e.g.                    occ_viz_geom pt1 pt2 cv1 cv2
    Each var is auto-classified as a point or a curve, so order/mix is free.
    Writes /tmp/occ_dv_<var1>.json; then type <var1> in the Debug Visualizer
    box.  Curves are sampled via Value(t) in the target (const call).
    """
    args = command.strip().split()
    if not args:
        result.SetError("Usage: occ_viz_geom <var1> <var2> [<var3> ...]")
        return
    frame = exe_ctx.GetFrame()
    if not frame or not frame.IsValid():
        result.SetError("No valid frame — stopped at a breakpoint?")
        return
    try:
        output = occ_geom(frame, args)
    except Exception as exc:
        output = json.dumps({"kind": {"text": True}, "text": f"Error: {exc}"})

    watch = args[0]
    path = f"{_OCC_DV_DIR}/occ_dv_{watch}.json"
    try:
        with open(path, "w") as fp:
            fp.write(output)
        result.AppendMessage(f"Written {path} — type '{watch}' in Debug Visualizer")
    except Exception as exc:
        result.AppendMessage(f"Could not write {path}: {exc}")


def occ_viz_pt_curve_cmd(debugger, command, exe_ctx, result, _internal_dict):
    """Debug Visualizer: a point and a curve in one graph (2-arg alias of occ_viz_geom).

    Usage (debug console):  occ_viz_pt_curve <pt_var> <curve_var>
    Writes /tmp/occ_dv_<pt_var>.json; then type <pt_var> in the Debug
    Visualizer box.  For more than two variables use occ_viz_geom.
    """
    occ_viz_geom_cmd(debugger, command, exe_ctx, result, _internal_dict)


# ---- Debug Visualizer payload pointer (struct __dv_payload *) --------------
# The watch template (settings.json) reads /tmp/occ_dv_<var>.json into a static
# buffer and returns a pointer to an INCOMPLETE struct (struct __dv_payload*).
# Debug Visualizer's source shows it will graph the variable's children whenever
# the evaluate response has variablesReference != 0 (ignoring the JSON), else it
# parses the `result` string as JSON.  Every ordinary string-bearing value is
# expandable and so fails here:
#   * char[N] array  -> N character children      -> graph of chars
#   * const char*    -> 1 deref child (*$1)        -> 2-node graph
#   * a synthetic 0-children provider              -> still adds a [raw] child
# A pointer to an INCOMPLETE type cannot be dereferenced, so it genuinely has no
# children -> variablesReference == 0, while CodeLLDB still shows the pointer's
# own summary.  dv_payload_summary surfaces the JSON as that summary, so Debug
# Visualizer parses and renders it.  The tag __dv_payload appears nowhere in
# OCCT/FreeCAD, so registering a summary for it affects nothing else.


def dv_payload_summary(value, _internal_dict):
    """Return the JSON payload the pointer addresses, verbatim, as the summary.

    CodeLLDB surfaces a value's summary as the DAP evaluate `result`, so making
    the summary the raw JSON object text lets Debug Visualizer parse it directly.
    Reads the whole NUL-terminated string from memory, so it is NOT capped by
    target.max-string-summary-length.
    """
    addr = _pointer(value)
    if addr == 0:
        return '{"kind":{"text":true},"text":"<null payload>"}'
    err = lldb.SBError()
    text = value.GetProcess().ReadCStringFromMemory(addr, 1 << 20, err)
    if not err.Success() or text is None:
        return '{"kind":{"text":true},"text":"<payload unreadable>"}'
    return text


# =============================================================================


def __lldb_init_module(debugger, _internal_dict):
    category = "OCCT"
    debugger.HandleCommand(f"type category define {category}")

    # The Debug Visualizer watch template returns the JSON payload as a pointer
    # to an incomplete struct (struct __dv_payload*): incomplete -> not
    # dereferenceable -> no children -> variablesReference == 0, so Debug
    # Visualizer parses the JSON instead of graphing the pointer.
    # dv_payload_summary surfaces that JSON as the pointer's summary.
    # See docs/occt-debugging.md.
    debugger.HandleCommand(
        "type summary add -w OCCT -x '__dv_payload' "
        "-F lldb_occt_formatters.dv_payload_summary"
    )
    # Belt-and-suspenders for any path that still hits LLDB's built-in C-string
    # summary (capped at target.max-string-summary-length, default 1024): raise
    # the cap so large point clouds are not truncated into invalid JSON.
    debugger.HandleCommand("settings set target.max-string-summary-length 1048576")

    debugger.HandleCommand(
        "type summary add -w OCCT -x '^opencascade::handle<.+>$' "
        "-F lldb_occt_formatters.handle_summary"
    )
    debugger.HandleCommand(
        "type summary add -w OCCT -x "
        "'^TopoDS_(Shape|Vertex|Edge|Wire|Face|Shell|Solid|CompSolid|Compound)$' "
        "-F lldb_occt_formatters.shape_summary"
    )
    debugger.HandleCommand(
        "type summary add -w OCCT -x "
        "'^(TopoDS|BRep)_T(Shape|Vertex|Edge|Wire|Face|Shell|Solid|CompSolid|Compound)$' "
        "-F lldb_occt_formatters.tshape_summary"
    )

    coordinate_types = "^(gp_(XY|XYZ|Pnt|Pnt2d|Vec|Vec2d|Dir|Dir2d))$"
    debugger.HandleCommand(
        f"type summary add -w {category} -x '{coordinate_types}' "
        "-F lldb_occt_formatters.coordinate_summary"
    )
    debugger.HandleCommand(
        f"type synthetic add -w {category} -x '{coordinate_types}' "
        "-l lldb_occt_formatters.CoordinateSyntheticProvider"
    )

    debugger.HandleCommand(
        "type summary add -w OCCT TCollection_AsciiString "
        "-F lldb_occt_formatters.ascii_string_summary"
    )
    debugger.HandleCommand(
        "type summary add -w OCCT TCollection_ExtendedString "
        "-F lldb_occt_formatters.extended_string_summary"
    )
    debugger.HandleCommand(
        "type summary add -w OCCT TopAbs_Orientation "
        "-F lldb_occt_formatters.orientation_summary"
    )
    debugger.HandleCommand(
        "type summary add -w OCCT -x "
        "'^NCollection_(List|Sequence|Vector|Array1|Map|DataMap|IndexedMap|IndexedDataMap)<.+>$' "
        "-F lldb_occt_formatters.collection_summary"
    )

    debugger.HandleCommand(f"type category enable {category}")

    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_save_cmd occ_save"
    )
    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_viz_shape_pts_cmd occ_viz_shape_pts"
    )
    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_viz_topo_cmd occ_viz_topo"
    )
    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_viz_pts_cmd occ_viz_pts"
    )
    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_viz_spine_cmd occ_viz_spine"
    )
    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_viz_pt_curve_cmd occ_viz_pt_curve"
    )
    debugger.HandleCommand(
        "command script add -f lldb_occt_formatters.occ_viz_geom_cmd occ_viz_geom"
    )

    print("OCCT LLDB formatters loaded.")

"""LLDB summaries and synthetic children for common OCCT value types."""

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


def __lldb_init_module(debugger, _internal_dict):
    category = "OCCT"
    debugger.HandleCommand(f"type category define {category}")

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
    print("OCCT LLDB formatters loaded.")

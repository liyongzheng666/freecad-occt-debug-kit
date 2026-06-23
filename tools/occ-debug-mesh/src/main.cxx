// =====================================================================
// occ-debug-mesh — BREP -> print-mesh (M2 phase 2, first cut).
//
// Reads a captured BREP, tessellates with OCCT relative deflection, and
// writes a print-mesh JSON: per-face submeshes in WORLD coordinates
// (accumulated TopLoc_Location applied), face_id = TopExp::MapShapes index,
// per-vertex normals via BRepLib (the same tool AIS_Shape uses), and a
// failed_faces list for faces that could not be tessellated (broken shapes).
//
// Decisions: docs/change-log.md §7. Format: Print/protocol/print-mesh.schema.json.
//
//   occ-debug-mesh <input.brep> [output.mesh.json]
//   occ-debug-mesh --make-test-box <out.brep>      (self-test fixture)
// =====================================================================
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_ListOfStatus.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepCheck_Status.hxx>
#include <BRepLib_ToolTriangulatedShape.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepTools.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Wire.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <gp.hxx>
#include <gp_Vec.hxx>
#include <Poly_Triangle.hxx>
#include <Poly_Triangulation.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopExp.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace {

// ---- deflection (docs/change-log.md §7) -----------------------------------
constexpr double kRelativeCoefficient = 0.002;  // ~2x coarser than OCCT default (0.001)
constexpr double kAngularDeflection = 0.5;       // = OCCT default Angle; clamped >= 0.2

std::string fmt(double v) {
  if (!std::isfinite(v)) return "0";  // last-resort guard so output stays valid JSON (D4)
  std::ostringstream s;
  s << std::setprecision(9) << v;  // doubles on the wire; viewer subtracts session origin
  return s.str();
}

void writeNumberArray(std::ostream& out, const std::vector<double>& values) {
  out << '[';
  for (size_t i = 0; i < values.size(); ++i) {
    if (i) out << ',';
    out << fmt(values[i]);
  }
  out << ']';
}

void writeIndexArray(std::ostream& out, const std::vector<int>& values) {
  out << '[';
  for (size_t i = 0; i < values.size(); ++i) {
    if (i) out << ',';
    out << values[i];
  }
  out << ']';
}

struct FaceMesh {
  std::string faceId;
  bool reversed = false;
  std::vector<double> positions;  // flat world xyz
  std::vector<int> indices;       // flat triangle indices
  std::vector<double> normals;    // flat world nxyz
};

// Tessellate one face into world coordinates. Returns false if the face has
// no usable triangulation (broken/unmeshable face -> failed_faces).
bool meshFace(const TopoDS_Face& face, const std::string& faceId, FaceMesh& out) {
  TopLoc_Location loc;
  Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, loc);
  if (tri.IsNull() || tri->NbNodes() == 0 || tri->NbTriangles() == 0) {
    return false;
  }
  const gp_Trsf trsf = loc.Transformation();  // accumulated parent locations -> world (M2-4)

  if (!tri->HasNormals()) {
    BRepLib_ToolTriangulatedShape::ComputeNormals(face, tri);  // same tool AIS_Shape uses
  }

  out.faceId = faceId;
  out.reversed = (face.Orientation() == TopAbs_REVERSED);

  for (Standard_Integer i = 1; i <= tri->NbNodes(); ++i) {
    const gp_Pnt p = tri->Node(i).Transformed(trsf);
    if (!std::isfinite(p.X()) || !std::isfinite(p.Y()) || !std::isfinite(p.Z())) {
      return false;  // degenerate node -> treat the whole face as unmeshable (V2/D4)
    }
    out.positions.push_back(p.X());
    out.positions.push_back(p.Y());
    out.positions.push_back(p.Z());
    gp_Dir n = tri->Normal(i).Transformed(trsf);
    if (out.reversed) n.Reverse();
    out.normals.push_back(n.X());
    out.normals.push_back(n.Y());
    out.normals.push_back(n.Z());
  }

  for (Standard_Integer t = 1; t <= tri->NbTriangles(); ++t) {
    Standard_Integer n1, n2, n3;
    tri->Triangle(t).Get(n1, n2, n3);
    // 1-based -> 0-based; flip winding for REVERSED faces so the front side
    // matches the (flipped) normals.
    if (out.reversed) {
      out.indices.push_back(n1 - 1);
      out.indices.push_back(n3 - 1);
      out.indices.push_back(n2 - 1);
    } else {
      out.indices.push_back(n1 - 1);
      out.indices.push_back(n2 - 1);
      out.indices.push_back(n3 - 1);
    }
  }
  return true;
}

// ---- defect diagnosis (BRepCheck_Analyzer = DRAW checkshape; §9) -----------
struct Defect {
  std::string category;  // -> defect.category
  std::string status;    // raw BRepCheck status name
  std::string faceId;    // ref (one of these set, or neither)
  std::string edgeId;
};

// Full name for every BRepCheck_Status (no information loss on unmapped codes).
std::string statusName(BRepCheck_Status s) {
#define OCC_DM_CASE(x) case BRepCheck_##x: return #x;
  switch (s) {
    OCC_DM_CASE(NoError)
    OCC_DM_CASE(InvalidPointOnCurve)
    OCC_DM_CASE(InvalidPointOnCurveOnSurface)
    OCC_DM_CASE(InvalidPointOnSurface)
    OCC_DM_CASE(No3DCurve)
    OCC_DM_CASE(Multiple3DCurve)
    OCC_DM_CASE(Invalid3DCurve)
    OCC_DM_CASE(NoCurveOnSurface)
    OCC_DM_CASE(InvalidCurveOnSurface)
    OCC_DM_CASE(InvalidCurveOnClosedSurface)
    OCC_DM_CASE(InvalidSameRangeFlag)
    OCC_DM_CASE(InvalidSameParameterFlag)
    OCC_DM_CASE(InvalidDegeneratedFlag)
    OCC_DM_CASE(FreeEdge)
    OCC_DM_CASE(InvalidMultiConnexity)
    OCC_DM_CASE(InvalidRange)
    OCC_DM_CASE(EmptyWire)
    OCC_DM_CASE(RedundantEdge)
    OCC_DM_CASE(SelfIntersectingWire)
    OCC_DM_CASE(NoSurface)
    OCC_DM_CASE(InvalidWire)
    OCC_DM_CASE(RedundantWire)
    OCC_DM_CASE(IntersectingWires)
    OCC_DM_CASE(InvalidImbricationOfWires)
    OCC_DM_CASE(EmptyShell)
    OCC_DM_CASE(RedundantFace)
    OCC_DM_CASE(InvalidImbricationOfShells)
    OCC_DM_CASE(UnorientableShape)
    OCC_DM_CASE(NotClosed)
    OCC_DM_CASE(NotConnected)
    OCC_DM_CASE(SubshapeNotInShape)
    OCC_DM_CASE(BadOrientation)
    OCC_DM_CASE(BadOrientationOfSubshape)
    OCC_DM_CASE(InvalidPolygonOnTriangulation)
    OCC_DM_CASE(InvalidToleranceValue)
    OCC_DM_CASE(EnclosedRegion)
    OCC_DM_CASE(CheckFail)
  }
#undef OCC_DM_CASE
  return "Unknown";
}

// BRepCheck status -> our defect.category (docs/change-log.md §7; unmapped -> other,
// but the raw status name is always preserved).
std::string statusCategory(BRepCheck_Status s) {
  switch (s) {
    case BRepCheck_SelfIntersectingWire:
    case BRepCheck_IntersectingWires:
    case BRepCheck_InvalidImbricationOfWires:
      return "self_intersection";
    case BRepCheck_NotClosed:
    case BRepCheck_FreeEdge:
      return "open_boundary";
    case BRepCheck_NoCurveOnSurface:
    case BRepCheck_InvalidCurveOnSurface:
    case BRepCheck_InvalidCurveOnClosedSurface:
    case BRepCheck_No3DCurve:
    case BRepCheck_Invalid3DCurve:
      return "invalid_pcurve";
    case BRepCheck_InvalidDegeneratedFlag:
    case BRepCheck_InvalidRange:
      return "degenerate";
    case BRepCheck_InvalidMultiConnexity:
      return "non_manifold";
    default:
      return "other";
  }
}

void collectInto(const BRepCheck_Analyzer& an, const TopoDS_Shape& sub,
                 const std::string& faceId, const std::string& edgeId,
                 std::set<std::string>& seen, std::vector<Defect>& out) {
  // Do NOT gate on IsValid(sub): a subshape can be valid standalone yet carry
  // a defect "in context" of its parent (e.g. a shell that is NotClosed within
  // its solid). Walk both the standalone status list and every context list.
  const Handle(BRepCheck_Result)& res = an.Result(sub);
  if (res.IsNull()) return;
  auto take = [&](const BRepCheck_ListOfStatus& list) {
    for (BRepCheck_ListOfStatus::Iterator it(list); it.More(); it.Next()) {
      const BRepCheck_Status st = it.Value();
      if (st == BRepCheck_NoError) continue;
      std::string key = std::string(statusName(st)) + "|" + faceId + "|" + edgeId;
      if (!seen.insert(key).second) continue;  // dedup across levels
      out.push_back({statusCategory(st), statusName(st), faceId, edgeId});
    }
  };
  take(res->Status());
  for (res->InitContextIterator(); res->MoreShapeInContext(); res->NextShapeInContext()) {
    take(res->StatusOnShape());
  }
}

std::vector<Defect> collectDefects(const TopoDS_Shape& shape,
                                   const TopTools_IndexedMapOfShape& faceMap,
                                   const TopTools_IndexedMapOfShape& edgeMap) {
  std::vector<Defect> out;
  std::set<std::string> seen;
  try {
    BRepCheck_Analyzer an(shape);
    if (an.IsValid()) return out;  // clean shape -> no defects
    for (Standard_Integer i = 1; i <= faceMap.Extent(); ++i) {
      collectInto(an, faceMap.FindKey(i), "F" + std::to_string(i), "", seen, out);
    }
    for (Standard_Integer i = 1; i <= edgeMap.Extent(); ++i) {
      collectInto(an, edgeMap.FindKey(i), "", "E" + std::to_string(i), seen, out);
    }
    // Wire-level defects (e.g. SelfIntersectingWire) carry no id of their own;
    // attach them to their parent face so the viewer can highlight it (M2-5).
    TopTools_IndexedDataMapOfShapeListOfShape wireFaces;
    TopExp::MapShapesAndAncestors(shape, TopAbs_WIRE, TopAbs_FACE, wireFaces);
    TopTools_IndexedMapOfShape wires;
    TopExp::MapShapes(shape, TopAbs_WIRE, wires);
    for (Standard_Integer i = 1; i <= wires.Extent(); ++i) {
      const TopoDS_Shape& wire = wires.FindKey(i);
      std::string faceId;
      if (wireFaces.Contains(wire) && !wireFaces.FindFromKey(wire).IsEmpty()) {
        faceId = "F" + std::to_string(faceMap.FindIndex(wireFaces.FindFromKey(wire).First()));
      }
      collectInto(an, wire, faceId, "", seen, out);
    }
    // Shell/solid-level defects (e.g. NotClosed) are scene-level, no face/edge id.
    for (TopAbs_ShapeEnum type : {TopAbs_SOLID, TopAbs_SHELL}) {
      TopTools_IndexedMapOfShape m;
      TopExp::MapShapes(shape, type, m);
      for (Standard_Integer i = 1; i <= m.Extent(); ++i) {
        collectInto(an, m.FindKey(i), "", "", seen, out);
      }
    }
  } catch (const Standard_Failure& e) {
    std::cerr << "[occ-debug-mesh] BRepCheck failed: " << e.GetMessageString() << "\n";
  }
  return out;
}

void writeDefects(const std::string& path, const std::vector<Defect>& defects) {
  std::ofstream out(path);
  if (!out) return;
  out << "[";
  for (size_t i = 0; i < defects.size(); ++i) {
    const Defect& d = defects[i];
    out << (i ? "," : "") << "\n  { \"category\": \"" << d.category
        << "\", \"source\": \"brepcheck\", \"severity\": \"error\", \"status\": \"BRepCheck_"
        << d.status << "\"";
    if (!d.faceId.empty() || !d.edgeId.empty()) {
      out << ", \"ref\": {";
      if (!d.faceId.empty()) out << " \"face_id\": \"" << d.faceId << "\"";
      if (!d.edgeId.empty()) out << (d.faceId.empty() ? " " : ", ") << "\"edge_id\": \"" << d.edgeId << "\"";
      out << " }";
    }
    out << " }";
  }
  out << (defects.empty() ? "]\n" : "\n]\n");
}

int convert(const std::string& inPath, const std::string& outPath) {
  TopoDS_Shape shape;
  BRep_Builder builder;
  if (!BRepTools::Read(shape, inPath.c_str(), builder) || shape.IsNull()) {
    std::cerr << "[occ-debug-mesh] failed to read BREP: " << inPath << "\n";
    return 2;
  }

  // Relative deflection: linDefl acts as a coefficient of edge size (OCCT
  // semantics); parallel meshing. The parameterized constructor performs the
  // meshing in place; broken faces are skipped (not fatal) below (V2).
  BRepMesh_IncrementalMesh mesher(shape, kRelativeCoefficient, Standard_True,
                                  kAngularDeflection, Standard_True);
  (void)mesher;

  TopTools_IndexedMapOfShape faces;
  TopExp::MapShapes(shape, TopAbs_FACE, faces);
  TopTools_IndexedMapOfShape edges;
  TopExp::MapShapes(shape, TopAbs_EDGE, edges);

  // Diagnose defects (face/edge ids share the same maps -> refs line up, M2-5).
  const std::vector<Defect> defects = collectDefects(shape, faces, edges);

  std::vector<FaceMesh> meshes;
  std::vector<std::string> failed;
  for (Standard_Integer i = 1; i <= faces.Extent(); ++i) {
    const TopoDS_Face face = TopoDS::Face(faces.FindKey(i));
    const std::string faceId = "F" + std::to_string(i);  // == MapShapes index (M2-5)
    FaceMesh fm;
    if (meshFace(face, faceId, fm)) {
      meshes.push_back(std::move(fm));
    } else {
      failed.push_back(faceId);
    }
  }

  std::ofstream out(outPath);
  if (!out) {
    std::cerr << "[occ-debug-mesh] cannot write: " << outPath << "\n";
    return 2;
  }
  out << "{\n  \"format_version\": \"1.0\",\n  \"unit\": \"mm\",\n";
  out << "  \"partial\": " << (failed.empty() ? "false" : "true") << ",\n";
  out << "  \"failed_faces\": [";
  for (size_t i = 0; i < failed.size(); ++i) {
    if (i) out << ", ";
    out << '"' << failed[i] << '"';
  }
  out << "],\n  \"faces\": [\n";
  for (size_t i = 0; i < meshes.size(); ++i) {
    const FaceMesh& m = meshes[i];
    out << "    { \"face_id\": \"" << m.faceId << "\", \"orientation\": \""
        << (m.reversed ? "REVERSED" : "FORWARD") << "\", \"positions\": ";
    writeNumberArray(out, m.positions);
    out << ", \"indices\": ";
    writeIndexArray(out, m.indices);
    out << ", \"normals\": ";
    writeNumberArray(out, m.normals);
    out << " }" << (i + 1 < meshes.size() ? "," : "") << "\n";
  }
  out << "  ],\n  \"edges\": []\n}\n";

  // Defects go to a sidecar (they are `defect` events, not mesh geometry; the
  // daemon turns them into events with entity_id filled in).
  std::string base = outPath;
  const std::string suffix = ".mesh.json";
  if (base.size() > suffix.size() &&
      base.compare(base.size() - suffix.size(), suffix.size(), suffix) == 0) {
    base = base.substr(0, base.size() - suffix.size());
  }
  const std::string defectsPath = base + ".defects.json";
  writeDefects(defectsPath, defects);

  std::cerr << "[occ-debug-mesh] " << inPath << " -> " << outPath << ": "
            << meshes.size() << " faces, " << failed.size() << " failed, "
            << defects.size() << " defects\n";
  return 0;
}

int makeTestBox(const std::string& outPath) {
  TopoDS_Shape box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape();
  if (!BRepTools::Write(box, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write test box: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote test box -> " << outPath << "\n";
  return 0;
}

// A deliberately invalid shape: a box with one face removed, wrapped as a
// solid -> BRepCheck reports the shell is NotClosed (open_boundary).
int makeTestBad(const std::string& outPath) {
  TopoDS_Shape box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape();
  BRep_Builder builder;
  TopoDS_Shell shell;
  builder.MakeShell(shell);
  Standard_Integer idx = 0;
  for (TopExp_Explorer ex(box, TopAbs_FACE); ex.More(); ex.Next()) {
    if (idx++ == 0) continue;  // drop one face -> open shell
    builder.Add(shell, ex.Current());
  }
  TopoDS_Solid solid = BRepBuilderAPI_MakeSolid(shell).Solid();
  if (!BRepTools::Write(solid, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write bad shape: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote open (invalid) box -> " << outPath << "\n";
  return 0;
}

// A box carrying a non-identity LOCATION (rotate 90 deg about Z, then translate
// by (100,200,300)) WITHOUT baking it into geometry -> exercises the world-
// coordinate path (M2-4): meshFace must apply the accumulated location.
int makeTestLocated(const std::string& outPath) {
  TopoDS_Shape box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape();
  gp_Trsf rot;
  rot.SetRotation(gp::OZ(), M_PI / 2.0);
  gp_Trsf tr;
  tr.SetTranslation(gp_Vec(100.0, 200.0, 300.0));
  const gp_Trsf trsf = tr.Multiplied(rot);  // apply rotation first, then translation
  TopoDS_Shape located = box.Moved(TopLoc_Location(trsf));
  if (!BRepTools::Write(located, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write located box: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote located box -> " << outPath << "\n";
  return 0;
}

// A self-intersecting (bowtie) planar face -> BRepCheck SelfIntersectingWire.
int makeTestSelfx(const std::string& outPath) {
  BRepBuilderAPI_MakePolygon poly(gp_Pnt(0, 0, 0), gp_Pnt(10, 10, 0),
                                  gp_Pnt(10, 0, 0), gp_Pnt(0, 10, 0), Standard_True);
  TopoDS_Face face = BRepBuilderAPI_MakeFace(poly.Wire(), Standard_True).Face();
  if (face.IsNull() || !BRepTools::Write(face, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write self-intersecting face: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote self-intersecting face -> " << outPath << "\n";
  return 0;
}

// A bare edge (no faces) -> exercises the V4 path (currently 0 faces).
int makeTestEdge(const std::string& outPath) {
  TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(10, 5, 2)).Edge();
  if (edge.IsNull() || !BRepTools::Write(edge, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write edge: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote bare edge -> " << outPath << "\n";
  return 0;
}

// Dump what BRepCheck_Analyzer reports for every subshape — debugging aid.
int diagnose(const std::string& inPath) {
  TopoDS_Shape shape;
  BRep_Builder builder;
  if (!BRepTools::Read(shape, inPath.c_str(), builder) || shape.IsNull()) {
    std::cerr << "[occ-debug-mesh] failed to read BREP: " << inPath << "\n";
    return 2;
  }
  BRepCheck_Analyzer an(shape);
  std::cerr << "IsValid(whole) = " << (an.IsValid() ? "true" : "false") << "\n";
  const struct { TopAbs_ShapeEnum t; const char* n; } types[] = {
    {TopAbs_SOLID, "SOLID"}, {TopAbs_SHELL, "SHELL"}, {TopAbs_FACE, "FACE"},
    {TopAbs_WIRE, "WIRE"}, {TopAbs_EDGE, "EDGE"}, {TopAbs_VERTEX, "VERTEX"}};
  for (const auto& ty : types) {
    TopTools_IndexedMapOfShape m;
    TopExp::MapShapes(shape, ty.t, m);
    for (Standard_Integer i = 1; i <= m.Extent(); ++i) {
      const TopoDS_Shape& sub = m.FindKey(i);
      std::cerr << ty.n << i << " valid=" << (an.IsValid(sub) ? "1" : "0");
      const Handle(BRepCheck_Result)& res = an.Result(sub);
      if (!res.IsNull()) {
        for (BRepCheck_ListOfStatus::Iterator it(res->Status()); it.More(); it.Next()) {
          std::cerr << " [" << statusName(it.Value()) << "]";
        }
        for (res->InitContextIterator(); res->MoreShapeInContext(); res->NextShapeInContext()) {
          for (BRepCheck_ListOfStatus::Iterator it(res->StatusOnShape()); it.More(); it.Next()) {
            std::cerr << " ctx[" << statusName(it.Value()) << "]";
          }
        }
      }
      std::cerr << "\n";
    }
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc >= 3 && std::string(argv[1]) == "--make-test-box") {
    return makeTestBox(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-bad") {
    return makeTestBad(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-located") {
    return makeTestLocated(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-selfx") {
    return makeTestSelfx(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-edge") {
    return makeTestEdge(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--diagnose") {
    return diagnose(argv[2]);
  }
  if (argc < 2) {
    std::cerr << "usage: occ-debug-mesh <input.brep> [output.mesh.json]\n"
              << "       occ-debug-mesh --make-test-box <out.brep>\n"
              << "       occ-debug-mesh --make-test-bad <out.brep>\n";
    return 1;
  }
  const std::string inPath = argv[1];
  const std::string outPath = (argc >= 3) ? argv[2] : (inPath + ".mesh.json");
  return convert(inPath, outPath);
}

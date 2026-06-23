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
#include <BRepLib_ToolTriangulatedShape.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepTools.hxx>
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

#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

// ---- deflection (docs/change-log.md §7) -----------------------------------
constexpr double kRelativeCoefficient = 0.002;  // ~2x coarser than OCCT default (0.001)
constexpr double kAngularDeflection = 0.5;       // = OCCT default Angle; clamped >= 0.2

std::string fmt(double v) {
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

int convert(const std::string& inPath, const std::string& outPath) {
  TopoDS_Shape shape;
  BRep_Builder builder;
  if (!BRepTools::Read(shape, inPath.c_str(), builder) || shape.IsNull()) {
    std::cerr << "[occ-debug-mesh] failed to read BREP: " << inPath << "\n";
    return 2;
  }

  // Relative deflection: linDefl acts as a coefficient of edge size (OCCT
  // semantics); parallel meshing. Broken faces are skipped, not fatal (V2).
  BRepMesh_IncrementalMesh mesher(shape, kRelativeCoefficient, Standard_True,
                                  kAngularDeflection, Standard_True);
  mesher.Perform();

  TopTools_IndexedMapOfShape faces;
  TopExp::MapShapes(shape, TopAbs_FACE, faces);

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

  std::cerr << "[occ-debug-mesh] " << inPath << " -> " << outPath << ": "
            << meshes.size() << " faces, " << failed.size() << " failed\n";
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

}  // namespace

int main(int argc, char** argv) {
  if (argc >= 3 && std::string(argv[1]) == "--make-test-box") {
    return makeTestBox(argv[2]);
  }
  if (argc < 2) {
    std::cerr << "usage: occ-debug-mesh <input.brep> [output.mesh.json]\n"
              << "       occ-debug-mesh --make-test-box <out.brep>\n";
    return 1;
  }
  const std::string inPath = argv[1];
  const std::string outPath = (argc >= 3) ? argv[2] : (inPath + ".mesh.json");
  return convert(inPath, outPath);
}

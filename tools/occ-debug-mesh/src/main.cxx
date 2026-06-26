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
#include <BRepBuilderAPI_MakeWire.hxx>  // non-manifold fixture (3 faces share one edge)
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_ListOfStatus.hxx>
#include <BRepCheck_Result.hxx>
#include <BRepCheck_Status.hxx>
#include <BRepLib_ToolTriangulatedShape.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
// ---- V2 mesh watchdog (wall-clock UserBreak via progress indicator) ----
#include <IMeshTools_Parameters.hxx>
#include <Message_ProgressIndicator.hxx>
#include <Message_ProgressRange.hxx>
// ---- §7 edge discretization ----
#include <BRepAdaptor_Curve.hxx>           // bare-edge / unmeshed-face 3D-curve adaptor (carries edge location)
#include <BRepBndLib.hxx>                   // shape bbox -> absolute deflection for GCPnts (TKTopAlgo)
#include <Bnd_Box.hxx>
#include <GCPnts_QuasiUniformDeflection.hxx>
#include <Poly_PolygonOnTriangulation.hxx> // on-face edge polyline (reuses the face triangulation)
// ---- NURBS test fixtures (B-spline surface/curve; TKGeomAlgo) ----
#include <GeomAPI_PointsToBSpline.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_OffsetCurve.hxx>
#include <Geom_OffsetSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <Precision.hxx>
// ---- P0a geometry/topology sidecar ----
#include <BRepAdaptor_Surface.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom_Surface.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Pnt2d.hxx>
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
#include <gp_Ax2.hxx>  // mirror fixture (reflect about a plane)
#include <gp_Vec.hxx>
#include <Poly_Triangle.hxx>
#include <Poly_Triangulation.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopExp.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>  // non-manifold fixture compound
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
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
  s.imbue(std::locale::classic());  // never emit comma-decimals -> always valid JSON
  // 17 sig digits round-trips a double: the viewer subtracts the session origin
  // AFTER parsing, so far-from-origin coords must survive serialization intact (M1).
  s << std::setprecision(17) << v;
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
  const bool mirror = trsf.IsNegative();       // reflecting Location (det<0) -> V9 winding/normal flip

  if (!tri->HasNormals()) {
    try {
      BRepLib_ToolTriangulatedShape::ComputeNormals(face, tri);  // same tool AIS_Shape uses
    } catch (const Standard_Failure&) {
      // degenerate surface: leave the face without normals rather than abort it.
    }
  }
  // Re-check: ComputeNormals can no-op on a degenerate face, and Normal(i) throws
  // Standard_NullObject when no normals exist. Emit normals only when present; the
  // schema marks them optional and the viewer recomputes when absent (B2).
  const bool hasNormals = tri->HasNormals();

  out.faceId = faceId;
  out.reversed = (face.Orientation() == TopAbs_REVERSED);
  // V9: a reflecting Location (det<0) flips triangle handedness, so the WINDING
  // must flip on (reversed XOR mirror). The NORMAL does not take the mirror term:
  // gp_Dir::Transformed already reflects the direction (it multiplies by the
  // det-+1 HVectorialPart then reverses for the negative scale), so only the
  // topological REVERSED flag flips the normal.
  const bool flipWinding = (out.reversed != mirror);

  for (Standard_Integer i = 1; i <= tri->NbNodes(); ++i) {
    const gp_Pnt p = tri->Node(i).Transformed(trsf);
    if (!std::isfinite(p.X()) || !std::isfinite(p.Y()) || !std::isfinite(p.Z())) {
      return false;  // degenerate node -> treat the whole face as unmeshable (V2/D4)
    }
    out.positions.push_back(p.X());
    out.positions.push_back(p.Y());
    out.positions.push_back(p.Z());
    if (hasNormals) {
      gp_Dir n = tri->Normal(i).Transformed(trsf);
      if (out.reversed) n.Reverse();  // mirror already handled by gp_Dir (see V9 note)
      out.normals.push_back(n.X());
      out.normals.push_back(n.Y());
      out.normals.push_back(n.Z());
    }
  }

  for (Standard_Integer t = 1; t <= tri->NbTriangles(); ++t) {
    Standard_Integer n1, n2, n3;
    tri->Triangle(t).Get(n1, n2, n3);
    // 1-based -> 0-based; flip winding on (reversed XOR mirror) so the front
    // side matches the normals (V9).
    if (flipWinding) {
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

// ---- §7 edge discretization (docs/change-log.md §7, README §7) -------------
struct EdgePolyline {
  std::string edgeId;
  std::vector<double> points;  // flat world xyz
};

// GCPnts wants an ABSOLUTE deflection, but our face mesh uses a relative
// coefficient. Derive a scale-invariant absolute value from the shape's
// world-space bbox diagonal (reuses the triangulation we just built), so bare
// edges discretize at roughly the same fidelity as the surfaces (§7 note).
double absoluteEdgeDeflection(const TopoDS_Shape& shape) {
  Bnd_Box box;
  BRepBndLib::Add(shape, box);  // useTriangulation=true: cheap, mesh already exists
  if (box.IsVoid()) return 1.0;  // no extent (e.g. empty) -> harmless fallback
  Standard_Real xmin, ymin, zmin, xmax, ymax, zmax;
  box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
  const double dx = xmax - xmin, dy = ymax - ymin, dz = zmax - zmin;
  const double diag = std::sqrt(dx * dx + dy * dy + dz * dz);
  const double d = diag * kRelativeCoefficient;
  return (std::isfinite(d) && d > 1e-7) ? d : 1e-3;  // floor so GCPnts never gets 0
}

// Push a finite world point onto a flat polyline; returns false on a non-finite
// coordinate (NaN guard, same policy as meshFace).
bool pushFinite(const gp_Pnt& p, std::vector<double>& pts) {
  if (!std::isfinite(p.X()) || !std::isfinite(p.Y()) || !std::isfinite(p.Z())) return false;
  pts.push_back(p.X());
  pts.push_back(p.Y());
  pts.push_back(p.Z());
  return true;
}

// Try the on-face path: reuse the edge's Poly_PolygonOnTriangulation on an
// already-triangulated ancestor face (free, and exactly coincident with the
// face mesh boundary). Fills `pts` (world coords) and returns true on success.
bool edgeFromFace(const TopoDS_Edge& edge,
                  const TopTools_ListOfShape& ancestorFaces,
                  std::vector<double>& pts) {
  for (TopTools_ListOfShape::Iterator it(ancestorFaces); it.More(); it.Next()) {
    TopLoc_Location loc;
    const TopoDS_Face face = TopoDS::Face(it.Value());
    Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, loc);
    if (tri.IsNull()) continue;
    // Same `loc` the triangulation was fetched with: poly node indices are
    // 1-based into tri's nodes (verified vs Poly_PolygonOnTriangulation.hxx).
    const Handle(Poly_PolygonOnTriangulation) poly =
        BRep_Tool::PolygonOnTriangulation(edge, tri, loc);
    if (poly.IsNull() || poly->NbNodes() < 2) continue;
    const gp_Trsf trsf = loc.Transformation();  // -> world (M2-4), same as meshFace
    pts.clear();
    bool ok = true;
    for (Standard_Integer k = 1; k <= poly->NbNodes(); ++k) {
      const Standard_Integer ni = poly->Node(k);
      if (ni < 1 || ni > tri->NbNodes()) { ok = false; break; }
      if (!pushFinite(tri->Node(ni).Transformed(trsf), pts)) { ok = false; break; }
    }
    if (ok && pts.size() >= 6) return true;  // >= 2 points
    pts.clear();
  }
  return false;
}

// Try the bare-curve path: discretize the edge's 3D curve directly. The
// BRepAdaptor_Curve composes the edge location, so Value() is already world.
bool edgeFromCurve(const TopoDS_Edge& edge, double deflection, std::vector<double>& pts) {
  try {
    BRepAdaptor_Curve adaptor(edge);
    GCPnts_QuasiUniformDeflection d(adaptor, deflection);
    if (!d.IsDone() || d.NbPoints() < 2) return false;
    pts.clear();
    for (Standard_Integer k = 1; k <= d.NbPoints(); ++k) {
      if (!pushFinite(d.Value(k), pts)) { pts.clear(); return false; }
    }
    return pts.size() >= 6;
  } catch (const Standard_Failure&) {
    return false;  // edge has no 3D curve (e.g. pure pcurve edge) -> skip
  }
}

// Discretize every (deduped) edge into a world-space polyline. edge_id shares
// the same TopExp::MapShapes index as defect refs (M2-5). On-face edges reuse
// the face mesh; bare edges fall back to the 3D curve (§7 dispatch, Q4).
std::vector<EdgePolyline> collectEdges(const TopoDS_Shape& shape,
                                       const TopTools_IndexedMapOfShape& edgeMap) {
  std::vector<EdgePolyline> out;
  TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
  TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
  const double deflection = absoluteEdgeDeflection(shape);

  for (Standard_Integer i = 1; i <= edgeMap.Extent(); ++i) {
    const TopoDS_Edge edge = TopoDS::Edge(edgeMap.FindKey(i));
    if (BRep_Tool::Degenerated(edge)) continue;  // seam/degenerate: no 3D curve to draw

    std::vector<double> pts;
    bool got = false;
    if (edgeFaces.Contains(edge)) {
      got = edgeFromFace(edge, edgeFaces.FindFromKey(edge), pts);
    }
    if (!got) got = edgeFromCurve(edge, deflection, pts);  // bare edge / unmeshed face

    if (got && pts.size() >= 6) {
      out.push_back({"E" + std::to_string(i), std::move(pts)});
    }
  }
  return out;
}

// ====================================================================
// P0a: geometry/topology sidecar (<base>.geom.json).
// Verified design: docs/occ-debug-mesh-export-design.md (§5/§8).
// Topology + geometry needed to *debug*, not just render: vertices+tolerance,
// curve/surface type, UV bounds + periodicity, edge flags/range/vertices/
// adjacent faces, and pcurves (UV; seam edges carry two, degenerate edges still
// carry one). All world coordinates; UV is in the face's parameter space.
// ====================================================================
const char* curveTypeName(GeomAbs_CurveType t) {
  switch (t) {
    case GeomAbs_Line: return "line";
    case GeomAbs_Circle: return "circle";
    case GeomAbs_Ellipse: return "ellipse";
    case GeomAbs_Hyperbola: return "hyperbola";
    case GeomAbs_Parabola: return "parabola";
    case GeomAbs_BezierCurve: return "bezier";
    case GeomAbs_BSplineCurve: return "bspline";
    case GeomAbs_OffsetCurve: return "offset";
    default: return "other";
  }
}

const char* surfaceTypeName(GeomAbs_SurfaceType t) {
  switch (t) {
    case GeomAbs_Plane: return "plane";
    case GeomAbs_Cylinder: return "cylinder";
    case GeomAbs_Cone: return "cone";
    case GeomAbs_Sphere: return "sphere";
    case GeomAbs_Torus: return "torus";
    case GeomAbs_BezierSurface: return "bezier";
    case GeomAbs_BSplineSurface: return "bspline";
    case GeomAbs_SurfaceOfRevolution: return "revolution";
    case GeomAbs_SurfaceOfExtrusion: return "extrusion";
    case GeomAbs_OffsetSurface: return "offset";
    default: return "other";
  }
}

// Unwrap a possibly-trimmed/offset curve|surface down to its B-spline basis
// (P0c control net). Returns null when there is no B-spline underneath.
Handle(Geom_BSplineCurve) asBSplineCurve(Handle(Geom_Curve) c) {
  for (int guard = 0; !c.IsNull() && guard < 8; ++guard) {
    if (Handle(Geom_BSplineCurve) bs = Handle(Geom_BSplineCurve)::DownCast(c)) return bs;
    if (Handle(Geom_TrimmedCurve) t = Handle(Geom_TrimmedCurve)::DownCast(c)) { c = t->BasisCurve(); continue; }
    if (Handle(Geom_OffsetCurve) o = Handle(Geom_OffsetCurve)::DownCast(c)) { c = o->BasisCurve(); continue; }
    break;
  }
  return Handle(Geom_BSplineCurve)();
}

Handle(Geom_BSplineSurface) asBSplineSurface(Handle(Geom_Surface) s) {
  for (int guard = 0; !s.IsNull() && guard < 8; ++guard) {
    if (Handle(Geom_BSplineSurface) bs = Handle(Geom_BSplineSurface)::DownCast(s)) return bs;
    if (Handle(Geom_RectangularTrimmedSurface) t = Handle(Geom_RectangularTrimmedSurface)::DownCast(s)) { s = t->BasisSurface(); continue; }
    if (Handle(Geom_OffsetSurface) o = Handle(Geom_OffsetSurface)::DownCast(s)) { s = o->BasisSurface(); continue; }
    break;
  }
  return Handle(Geom_BSplineSurface)();
}

// NURBS control net (poles in WORLD coords). For a curve nbV=0 (poles is the
// control polygon); for a surface nbU*nbV poles, row-major (u outer, v inner).
struct ControlNet {
  bool present = false;
  int degreeU = 0, degreeV = 0, nbU = 0, nbV = 0;
  bool rational = false, periodicU = false, periodicV = false;
  std::vector<double> poles;    // flat world xyz
  std::vector<double> weights;  // rational only
};

ControlNet curveControlNet(const TopoDS_Edge& edge) {
  ControlNet cn;
  TopLoc_Location loc;
  Standard_Real f, l;
  Handle(Geom_BSplineCurve) bs = asBSplineCurve(BRep_Tool::Curve(edge, loc, f, l));
  if (bs.IsNull()) return cn;
  const gp_Trsf trsf = loc.Transformation();
  cn.present = true;
  cn.degreeU = bs->Degree();
  cn.nbU = bs->NbPoles();
  cn.rational = bs->IsRational();
  cn.periodicU = bs->IsPeriodic();
  for (Standard_Integer i = 1; i <= bs->NbPoles(); ++i) {
    const gp_Pnt p = bs->Pole(i).Transformed(trsf);
    cn.poles.push_back(p.X());
    cn.poles.push_back(p.Y());
    cn.poles.push_back(p.Z());
    if (cn.rational) cn.weights.push_back(bs->Weight(i));
  }
  return cn;
}

ControlNet surfaceControlNet(const TopoDS_Face& face) {
  ControlNet cn;
  TopLoc_Location loc;
  Handle(Geom_BSplineSurface) bs = asBSplineSurface(BRep_Tool::Surface(face, loc));
  if (bs.IsNull()) return cn;
  const gp_Trsf trsf = loc.Transformation();
  cn.present = true;
  cn.degreeU = bs->UDegree();
  cn.degreeV = bs->VDegree();
  cn.nbU = bs->NbUPoles();
  cn.nbV = bs->NbVPoles();
  cn.rational = bs->IsURational() || bs->IsVRational();
  cn.periodicU = bs->IsUPeriodic();
  cn.periodicV = bs->IsVPeriodic();
  for (Standard_Integer i = 1; i <= bs->NbUPoles(); ++i) {     // u outer
    for (Standard_Integer j = 1; j <= bs->NbVPoles(); ++j) {   // v inner (row-major)
      const gp_Pnt p = bs->Pole(i, j).Transformed(trsf);
      cn.poles.push_back(p.X());
      cn.poles.push_back(p.Y());
      cn.poles.push_back(p.Z());
      if (cn.rational) cn.weights.push_back(bs->Weight(i, j));
    }
  }
  return cn;
}

struct VertexGeom {
  std::string id;
  double x, y, z, tol;
};
struct PCurve {
  std::string faceId;
  bool isSeam;
  int index;
  std::vector<double> uv;  // flat u,v in the face's parameter space
};
struct EdgeGeom {
  std::string id;
  std::string curveType;
  double tol = 0;
  double rangeFirst = 0, rangeLast = 0;
  bool degenerate = false, sameParameter = false, closed = false;
  std::string startVertex, endVertex;
  std::vector<std::string> adjacentFaces;
  std::vector<PCurve> pcurves;
  ControlNet control;
};
struct FaceGeom {
  std::string id;
  std::string surfaceType;
  double umin = 0, umax = 0, vmin = 0, vmax = 0, tol = 0;
  bool uPeriodic = false, vPeriodic = false, uClosed = false, vClosed = false;
  ControlNet control;
};

std::vector<VertexGeom> collectVertices(const TopTools_IndexedMapOfShape& vertexMap) {
  std::vector<VertexGeom> out;
  for (Standard_Integer i = 1; i <= vertexMap.Extent(); ++i) {
    const TopoDS_Vertex v = TopoDS::Vertex(vertexMap.FindKey(i));
    const gp_Pnt p = BRep_Tool::Pnt(v);  // located -> world
    out.push_back({"V" + std::to_string(i), p.X(), p.Y(), p.Z(), BRep_Tool::Tolerance(v)});
  }
  return out;
}

std::vector<FaceGeom> collectFaceGeom(const TopTools_IndexedMapOfShape& faceMap) {
  std::vector<FaceGeom> out;
  for (Standard_Integer i = 1; i <= faceMap.Extent(); ++i) {
    const TopoDS_Face face = TopoDS::Face(faceMap.FindKey(i));
    FaceGeom g;
    g.id = "F" + std::to_string(i);
    g.tol = BRep_Tool::Tolerance(face);
    try {
      BRepAdaptor_Surface as(face);
      g.surfaceType = surfaceTypeName(as.GetType());
    } catch (const Standard_Failure&) {
      g.surfaceType = "other";
    }
    BRepTools::UVBounds(face, g.umin, g.umax, g.vmin, g.vmax);
    TopLoc_Location loc;
    Handle(Geom_Surface) s = BRep_Tool::Surface(face, loc);
    if (!s.IsNull()) {
      g.uPeriodic = s->IsUPeriodic();
      g.vPeriodic = s->IsVPeriodic();
      g.uClosed = s->IsUClosed();
      g.vClosed = s->IsVClosed();
    }
    g.control = surfaceControlNet(face);  // NURBS control net (P0c)
    out.push_back(std::move(g));
  }
  return out;
}

// Sample a pcurve (2D parameter-space curve) into a flat u,v polyline. Plain
// lines need 2 points; everything else gets a uniform parameter sampling.
std::vector<double> discretizePCurve(const Handle(Geom2d_Curve)& pc, double f, double l) {
  std::vector<double> uv;
  if (pc.IsNull() || !(l > f)) return uv;
  const int n = Handle(Geom2d_Line)::DownCast(pc).IsNull() ? 24 : 2;
  for (int i = 0; i < n; ++i) {
    const double t = f + (l - f) * (double(i) / (n - 1));
    const gp_Pnt2d p = pc->Value(t);
    if (!std::isfinite(p.X()) || !std::isfinite(p.Y())) continue;
    uv.push_back(p.X());
    uv.push_back(p.Y());
  }
  return uv;
}

std::vector<EdgeGeom> collectEdgeGeom(const TopoDS_Shape& shape,
                                      const TopTools_IndexedMapOfShape& edgeMap,
                                      const TopTools_IndexedMapOfShape& faceMap,
                                      const TopTools_IndexedMapOfShape& vertexMap) {
  std::vector<EdgeGeom> out;
  TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
  TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
  for (Standard_Integer i = 1; i <= edgeMap.Extent(); ++i) {
    const TopoDS_Edge edge = TopoDS::Edge(edgeMap.FindKey(i));
    EdgeGeom g;
    g.id = "E" + std::to_string(i);
    g.degenerate = BRep_Tool::Degenerated(edge);
    g.sameParameter = BRep_Tool::SameParameter(edge);
    g.closed = BRep_Tool::IsClosed(edge);
    g.tol = BRep_Tool::Tolerance(edge);
    g.curveType = "none";
    if (!g.degenerate) {
      try {
        BRepAdaptor_Curve ac(edge);  // throws if no 3D curve (pure-pcurve edge)
        g.curveType = curveTypeName(ac.GetType());
        g.rangeFirst = ac.FirstParameter();
        g.rangeLast = ac.LastParameter();
      } catch (const Standard_Failure&) {
        g.curveType = "none";
      }
    }
    g.control = curveControlNet(edge);  // NURBS control polygon (P0c)
    const TopoDS_Vertex v1 = TopExp::FirstVertex(edge, Standard_True);
    const TopoDS_Vertex v2 = TopExp::LastVertex(edge, Standard_True);
    if (!v1.IsNull() && vertexMap.Contains(v1)) g.startVertex = "V" + std::to_string(vertexMap.FindIndex(v1));
    if (!v2.IsNull() && vertexMap.Contains(v2)) g.endVertex = "V" + std::to_string(vertexMap.FindIndex(v2));
    if (edgeFaces.Contains(edge)) {
      std::set<std::string> seenFaces;  // dedup (a seam edge bounds its face twice)
      for (TopTools_ListOfShape::Iterator it(edgeFaces.FindFromKey(edge)); it.More(); it.Next()) {
        const TopoDS_Face face = TopoDS::Face(it.Value());
        const std::string faceId = "F" + std::to_string(faceMap.FindIndex(face));
        if (!seenFaces.insert(faceId).second) continue;
        g.adjacentFaces.push_back(faceId);
        const bool seam = BRep_Tool::IsClosed(edge, face);
        Standard_Real f2 = 0, l2 = 0;
        const Handle(Geom2d_Curve) pc1 = BRep_Tool::CurveOnSurface(edge, face, f2, l2);
        std::vector<double> uv1 = discretizePCurve(pc1, f2, l2);
        if (!uv1.empty()) g.pcurves.push_back({faceId, seam, 1, std::move(uv1)});
        if (seam) {  // the other side of the seam = the reversed edge's pcurve
          Standard_Real f3 = 0, l3 = 0;
          const Handle(Geom2d_Curve) pc2 =
              BRep_Tool::CurveOnSurface(TopoDS::Edge(edge.Reversed()), face, f3, l3);
          std::vector<double> uv2 = discretizePCurve(pc2, f3, l3);
          if (!uv2.empty()) g.pcurves.push_back({faceId, seam, 2, std::move(uv2)});
        }
      }
    }
    out.push_back(std::move(g));
  }
  return out;
}

void writeControl(std::ostream& out, const ControlNet& cn) {
  if (!cn.present) return;
  out << ", \"control\": { \"degree_u\": " << cn.degreeU << ", \"degree_v\": " << cn.degreeV
      << ", \"nb_u\": " << cn.nbU << ", \"nb_v\": " << cn.nbV
      << ", \"rational\": " << (cn.rational ? "true" : "false")
      << ", \"periodic_u\": " << (cn.periodicU ? "true" : "false")
      << ", \"periodic_v\": " << (cn.periodicV ? "true" : "false") << ", \"poles\": ";
  writeNumberArray(out, cn.poles);  // flat world xyz, surface poles row-major (u outer, v inner)
  if (cn.rational) {
    out << ", \"weights\": ";
    writeNumberArray(out, cn.weights);
  }
  out << " }";
}

void writeGeom(const std::string& path, const std::vector<VertexGeom>& verts,
               const std::vector<EdgeGeom>& edges, const std::vector<FaceGeom>& faces) {
  std::ofstream out(path);
  if (!out) return;
  auto b = [](bool v) { return v ? "true" : "false"; };
  out << "{\n  \"format_version\": \"1.0\",\n  \"unit\": \"mm\",\n";

  out << "  \"vertices\": [";
  for (size_t i = 0; i < verts.size(); ++i) {
    const VertexGeom& v = verts[i];
    out << (i ? "," : "") << "\n    { \"id\": \"" << v.id << "\", \"point\": [" << fmt(v.x) << ","
        << fmt(v.y) << "," << fmt(v.z) << "], \"tolerance\": " << fmt(v.tol) << " }";
  }
  out << (verts.empty() ? "],\n" : "\n  ],\n");

  out << "  \"faces\": [";
  for (size_t i = 0; i < faces.size(); ++i) {
    const FaceGeom& f = faces[i];
    out << (i ? "," : "") << "\n    { \"id\": \"" << f.id << "\", \"surface_type\": \"" << f.surfaceType
        << "\", \"uv_bounds\": [" << fmt(f.umin) << "," << fmt(f.umax) << "," << fmt(f.vmin) << ","
        << fmt(f.vmax) << "], \"periodic_u\": " << b(f.uPeriodic) << ", \"periodic_v\": " << b(f.vPeriodic)
        << ", \"closed_u\": " << b(f.uClosed) << ", \"closed_v\": " << b(f.vClosed)
        << ", \"tolerance\": " << fmt(f.tol);
    writeControl(out, f.control);
    out << " }";
  }
  out << (faces.empty() ? "],\n" : "\n  ],\n");

  out << "  \"edges\": [";
  for (size_t i = 0; i < edges.size(); ++i) {
    const EdgeGeom& e = edges[i];
    out << (i ? "," : "") << "\n    { \"id\": \"" << e.id << "\", \"curve_type\": \"" << e.curveType
        << "\", \"tolerance\": " << fmt(e.tol) << ", \"range\": [" << fmt(e.rangeFirst) << ","
        << fmt(e.rangeLast) << "], \"degenerate\": " << b(e.degenerate) << ", \"same_parameter\": "
        << b(e.sameParameter) << ", \"closed\": " << b(e.closed);
    if (!e.startVertex.empty()) out << ", \"start_vertex\": \"" << e.startVertex << "\"";
    if (!e.endVertex.empty()) out << ", \"end_vertex\": \"" << e.endVertex << "\"";
    out << ", \"adjacent_faces\": [";
    for (size_t k = 0; k < e.adjacentFaces.size(); ++k) out << (k ? "," : "") << "\"" << e.adjacentFaces[k] << "\"";
    out << "], \"pcurves\": [";
    for (size_t k = 0; k < e.pcurves.size(); ++k) {
      const PCurve& pc = e.pcurves[k];
      out << (k ? "," : "") << " { \"face_id\": \"" << pc.faceId << "\", \"is_seam\": " << b(pc.isSeam)
          << ", \"index\": " << pc.index << ", \"uv\": ";
      writeNumberArray(out, pc.uv);
      out << " }";
    }
    out << "]";
    writeControl(out, e.control);
    out << " }";
  }
  out << (edges.empty() ? "]\n" : "\n  ]\n");
  out << "}\n";
}

// ---- defect diagnosis (BRepCheck_Analyzer = DRAW checkshape; §9) -----------
struct Defect {
  std::string category;  // -> defect.category
  std::string source;    // -> defect.source: "brepcheck" | "topology"
  std::string status;    // full status string as emitted (e.g. "BRepCheck_NotClosed")
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
      out.push_back({statusCategory(st), "brepcheck",
                     std::string("BRepCheck_") + statusName(st), faceId, edgeId});
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

  // Edge -> distinct adjacent faces. Non-oriented hashing, so a seam edge's two
  // uses on one face collapse to a single distinct face. Shared by the
  // non-manifold (§9) and free-edge (R3) passes below.
  TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
  TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
  auto distinctFaceCount = [&](const TopoDS_Edge& e) -> int {
    if (!edgeFaces.Contains(e)) return 0;
    std::set<int> ids;
    for (TopTools_ListOfShape::Iterator it(edgeFaces.FindFromKey(e)); it.More(); it.Next())
      ids.insert(faceMap.FindIndex(it.Value()));
    return static_cast<int>(ids.size());
  };

  // (§9) Non-manifold edges: pure topology, run BEFORE any BRepCheck early-return
  // (a 3-faces-sharing-an-edge compound can be "valid" per BRepCheck). BRepCheck
  // never reports this, and neither does bopcheck (verified against 7.8.1).
  for (Standard_Integer i = 1; i <= edgeMap.Extent(); ++i) {
    const TopoDS_Edge e = TopoDS::Edge(edgeMap.FindKey(i));
    if (BRep_Tool::Degenerated(e)) continue;
    if (distinctFaceCount(e) > 2) {  // 1=free, 2=manifold, >2=non-manifold
      const std::string id = "E" + std::to_string(i);
      if (seen.insert("NonManifoldEdge||" + id).second)
        out.push_back({"non_manifold", "topology", "NonManifoldEdge", "", id});
    }
  }

  try {
    BRepCheck_Analyzer an(shape);
    if (an.IsValid()) return out;  // clean (apart from any non-manifold edges above)
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
    // (R3) If the shape is NotClosed, localize the open boundary onto its free
    // edges (exactly one adjacent face) so the viewer can highlight the gap.
    // BRepCheck reports NotClosed only at shell context level (verified), so this
    // is purely additive; the scene-level NotClosed above is retained.
    bool notClosed = false;
    for (const Defect& d : out)
      if (d.status == "BRepCheck_NotClosed") { notClosed = true; break; }
    if (notClosed) {
      for (Standard_Integer i = 1; i <= edgeMap.Extent(); ++i) {
        const TopoDS_Edge e = TopoDS::Edge(edgeMap.FindKey(i));
        if (BRep_Tool::Degenerated(e)) continue;
        if (distinctFaceCount(e) == 1) {  // bounded by a single face -> free edge
          const std::string id = "E" + std::to_string(i);
          if (seen.insert("FreeEdge||" + id).second)
            out.push_back({"open_boundary", "topology", "FreeEdge", "", id});
        }
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
        << "\", \"source\": \"" << d.source << "\", \"severity\": \"error\", \"status\": \""
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

// V2 mesh watchdog: a progress indicator whose UserBreak() trips after a
// wall-clock budget. BRepMesh polls UserBreak per-face (BRepMesh_FaceDiscret),
// so on expiry the remaining faces are left untriangulated -> they fall into
// failed_faces (partial=true), bounding runaway meshing at FACE granularity.
// A single face hung *inside* its own discretization still needs an external
// hard timeout (Layer 2, the daemon's job). Opt-in via --timeout; off by default.
class WallClockBreak : public Message_ProgressIndicator {
public:
  explicit WallClockBreak(double seconds)
      : myDeadline(std::chrono::steady_clock::now() +
                   std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                       std::chrono::duration<double>(seconds))) {}
  Standard_Boolean UserBreak() override {
    return std::chrono::steady_clock::now() >= myDeadline;
  }
  // Pure-virtual in the base; we render no progress UI, only gate on UserBreak.
  void Show(const Message_ProgressScope&, const Standard_Boolean) override {}

private:
  std::chrono::steady_clock::time_point myDeadline;
};

int convert(const std::string& inPath, const std::string& outPath, double timeoutSec = 0.0) {
  TopoDS_Shape shape;
  BRep_Builder builder;
  if (!BRepTools::Read(shape, inPath.c_str(), builder) || shape.IsNull()) {
    std::cerr << "[occ-debug-mesh] failed to read BREP: " << inPath << "\n";
    return 2;
  }

  // Relative deflection: linDefl acts as a coefficient of edge size (OCCT
  // semantics); parallel meshing. The parameterized constructor performs the
  // meshing in place; broken faces are skipped (not fatal) below (V2).
  // A pathological shape can make the kernel *throw* (not just fail a face);
  // catch it so faces without triangulation simply fall into failed_faces
  // rather than crashing the whole tool (V2/D4: "坏 shape 不崩").
  try {
    if (timeoutSec > 0.0) {
      // Opt-in watchdog path: identical deflection settings, but driven through
      // IMeshTools_Parameters so we can pass a wall-clock progress range (V2).
      IMeshTools_Parameters params;
      params.Deflection = kRelativeCoefficient;
      params.Angle = kAngularDeflection;
      params.Relative = Standard_True;
      params.InParallel = Standard_True;
      Handle(Message_ProgressIndicator) watchdog = new WallClockBreak(timeoutSec);
      BRepMesh_IncrementalMesh mesher(shape, params, watchdog->Start());
      (void)mesher;
    } else {
      BRepMesh_IncrementalMesh mesher(shape, kRelativeCoefficient, Standard_True,
                                      kAngularDeflection, Standard_True);
      (void)mesher;
    }
  } catch (const Standard_Failure& e) {
    std::cerr << "[occ-debug-mesh] meshing raised: " << e.GetMessageString()
              << " (continuing; unmeshed faces -> failed_faces)\n";
  }

  TopTools_IndexedMapOfShape faces;
  TopExp::MapShapes(shape, TopAbs_FACE, faces);
  TopTools_IndexedMapOfShape edges;
  TopExp::MapShapes(shape, TopAbs_EDGE, edges);
  TopTools_IndexedMapOfShape verts;
  TopExp::MapShapes(shape, TopAbs_VERTEX, verts);

  // Diagnose defects (face/edge ids share the same maps -> refs line up, M2-5).
  const std::vector<Defect> defects = collectDefects(shape, faces, edges);

  // Edge polylines: on-face edges reuse the face mesh, bare edges discretize
  // the 3D curve (§7). edge_id == MapShapes index, same as defect refs.
  const std::vector<EdgePolyline> edgePolys = collectEdges(shape, edges);

  std::vector<FaceMesh> meshes;
  std::vector<std::string> failed;
  for (Standard_Integer i = 1; i <= faces.Extent(); ++i) {
    const TopoDS_Face face = TopoDS::Face(faces.FindKey(i));
    const std::string faceId = "F" + std::to_string(i);  // == MapShapes index (M2-5)
    FaceMesh fm;
    bool ok = false;
    try {
      ok = meshFace(face, faceId, fm);
    } catch (const Standard_Failure&) {
      ok = false;  // a broken face raised inside the kernel -> failed_faces, not a crash (B1)
    }
    if (ok) {
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
    if (!m.normals.empty()) {  // absent (not empty) -> viewer recomputes (B2; schema-optional)
      out << ", \"normals\": ";
      writeNumberArray(out, m.normals);
    }
    out << " }" << (i + 1 < meshes.size() ? "," : "") << "\n";
  }
  out << "  ],\n  \"edges\": [";
  for (size_t i = 0; i < edgePolys.size(); ++i) {
    const EdgePolyline& e = edgePolys[i];
    out << (i ? "," : "") << "\n    { \"edge_id\": \"" << e.edgeId << "\", \"points\": ";
    writeNumberArray(out, e.points);
    out << " }";
  }
  out << (edgePolys.empty() ? "]\n}\n" : "\n  ]\n}\n");

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

  // Geometry/topology sidecar (P0a): vertices+tolerance, curve/surface types,
  // UV bounds + periodicity, edge flags/range/adjacency, pcurves (UV).
  const std::string geomPath = base + ".geom.json";
  writeGeom(geomPath, collectVertices(verts), collectEdgeGeom(shape, edges, faces, verts),
            collectFaceGeom(faces));

  std::cerr << "[occ-debug-mesh] " << inPath << " -> " << outPath << ": "
            << meshes.size() << " faces, " << edgePolys.size() << " edges, "
            << verts.Extent() << " verts, " << failed.size() << " failed, "
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

// A genuine NURBS (B-spline) surface built DIRECTLY from a clean 6x6 control
// grid (degree 3), so the control net IS that tidy wavy grid — no interpolation
// overshoot. One free-form face whose 4 boundary edges are B-spline curves;
// exercises the curved on-face edge path (multi-point polylines) and gives a
// well-behaved control net to visualize.
int makeTestNurbs(const std::string& outPath) {
  const Standard_Integer nu = 6, nv = 6, deg = 3;
  TColgp_Array2OfPnt poles(1, nu, 1, nv);
  for (Standard_Integer i = 1; i <= nu; ++i) {
    for (Standard_Integer j = 1; j <= nv; ++j) {
      const double x = (i - 1) * 6.0;  // 0..30
      const double y = (j - 1) * 6.0;  // 0..30
      poles.SetValue(i, j, gp_Pnt(x, y, 6.0 * std::sin(x * 0.2) * std::cos(y * 0.2)));
    }
  }
  // Clamped uniform knot vector: nk = n-deg+1 distinct knots, end mult deg+1.
  const Standard_Integer nk = nu - deg + 1;  // 4 for nu=6, deg=3
  TColStd_Array1OfReal knots(1, nk);
  TColStd_Array1OfInteger mults(1, nk);
  for (Standard_Integer k = 1; k <= nk; ++k) {
    knots.SetValue(k, k - 1);
    mults.SetValue(k, 1);
  }
  mults.SetValue(1, deg + 1);
  mults.SetValue(nk, deg + 1);
  Handle(Geom_BSplineSurface) surf =
      new Geom_BSplineSurface(poles, knots, knots, mults, mults, deg, deg);
  if (surf.IsNull()) {
    std::cerr << "[occ-debug-mesh] B-spline surface build failed\n";
    return 2;
  }
  TopoDS_Face face = BRepBuilderAPI_MakeFace(surf, Precision::Confusion()).Face();
  if (face.IsNull() || !BRepTools::Write(face, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write NURBS face: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote NURBS B-spline surface -> " << outPath << "\n";
  return 0;
}

// A bare NURBS (B-spline) curve fitted through wavy points -> one free-form
// edge with no face. Exercises the bare-curve path (GCPnts) on a real curve:
// the polyline has many deflection-spaced points (vs the 2 of a straight edge).
int makeTestBsplineEdge(const std::string& outPath) {
  const Standard_Integer n = 7;
  TColgp_Array1OfPnt pts(1, n);
  for (Standard_Integer i = 1; i <= n; ++i) {
    const double t = (i - 1) * 5.0;  // 0..30
    pts.SetValue(i, gp_Pnt(t, 5.0 * std::sin(t * 0.25), 3.0 * std::cos(t * 0.3)));
  }
  Handle(Geom_BSplineCurve) curve = GeomAPI_PointsToBSpline(pts).Curve();
  if (curve.IsNull()) {
    std::cerr << "[occ-debug-mesh] B-spline curve fit failed\n";
    return 2;
  }
  TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(curve).Edge();
  if (edge.IsNull() || !BRepTools::Write(edge, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write B-spline edge: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote NURBS B-spline edge -> " << outPath << "\n";
  return 0;
}

// Analytic periodic/closed fixtures for the geom/UV path (P0a):
//   cylinder -> cylindrical face (1 seam edge, U-periodic) + 2 circle edges
//   sphere   -> spherical face (seam + 2 pole DEGENERATE edges)
//   torus    -> toroidal face (U and V periodic)
int makeTestCylinder(const std::string& outPath) {
  TopoDS_Shape s = BRepPrimAPI_MakeCylinder(5.0, 20.0).Shape();
  if (!BRepTools::Write(s, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write cylinder: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote cylinder -> " << outPath << "\n";
  return 0;
}

int makeTestSphere(const std::string& outPath) {
  TopoDS_Shape s = BRepPrimAPI_MakeSphere(8.0).Shape();
  if (!BRepTools::Write(s, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write sphere: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote sphere -> " << outPath << "\n";
  return 0;
}

int makeTestTorus(const std::string& outPath) {
  TopoDS_Shape s = BRepPrimAPI_MakeTorus(10.0, 3.0).Shape();
  if (!BRepTools::Write(s, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write torus: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote torus -> " << outPath << "\n";
  return 0;
}

// A box carrying a MIRROR Location (reflect about the YZ plane -> x flips, then
// translate into +X) so the accumulated Location has det < 0 (gp_Trsf::IsNegative).
// Exercises V9: winding + normals must stay outward under a reflecting Location,
// not just under topological REVERSED. World bbox: X[40,50] Y[0,20] Z[0,30].
int makeTestMirror(const std::string& outPath) {
  TopoDS_Shape box = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape();
  gp_Trsf mir;
  mir.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)));  // mirror plane = YZ (x -> -x)
  gp_Trsf tr;
  tr.SetTranslation(gp_Vec(50.0, 0.0, 0.0));                 // shift mirrored box into +X
  // OCCT forbids a non-rigid (mirror) trsf in Moved/Move (Standard_DomainError);
  // Located(loc, /*theRaiseExc=*/false) bypasses that guard and deliberately puts
  // the reflecting transform into the Location — exactly the det<0 case meshFace
  // must handle (V9). This is how a mirror Location actually reaches the mesher.
  TopoDS_Shape mirrored = box.Located(TopLoc_Location(tr.Multiplied(mir)), Standard_False);
  if (!BRepTools::Write(mirrored, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write mirrored box: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote mirrored box -> " << outPath << "\n";
  return 0;
}

// Three planar faces fanning out from ONE shared edge -> a non-manifold edge
// (adjacent to 3 faces). The shared TopoDS_Edge object is reused in all three
// wires, so TopExp's non-oriented hashing keys it once with three FACE ancestors.
// BRepCheck does not flag this (nor does bopcheck) — we detect it topologically.
int makeTestNonManifold(const std::string& outPath) {
  const gp_Pnt a(0, 0, 0), b(0, 0, 10);
  TopoDS_Edge shared = BRepBuilderAPI_MakeEdge(a, b).Edge();
  BRep_Builder builder;
  TopoDS_Compound comp;
  builder.MakeCompound(comp);
  const gp_Vec dirs[3] = {gp_Vec(10, 0, 0), gp_Vec(-5, 8, 0), gp_Vec(-5, -8, 0)};
  for (const gp_Vec& d : dirs) {
    const gp_Pnt c1 = a.Translated(d), c2 = b.Translated(d);
    TopoDS_Wire w = BRepBuilderAPI_MakeWire(shared,
                                            BRepBuilderAPI_MakeEdge(b, c2).Edge(),
                                            BRepBuilderAPI_MakeEdge(c2, c1).Edge(),
                                            BRepBuilderAPI_MakeEdge(c1, a).Edge());
    TopoDS_Face f = BRepBuilderAPI_MakeFace(w, Standard_True).Face();
    if (f.IsNull()) {
      std::cerr << "[occ-debug-mesh] non-manifold face build failed\n";
      return 2;
    }
    builder.Add(comp, f);
  }
  if (!BRepTools::Write(comp, outPath.c_str())) {
    std::cerr << "[occ-debug-mesh] failed to write non-manifold shape: " << outPath << "\n";
    return 2;
  }
  std::cerr << "[occ-debug-mesh] wrote non-manifold (3 faces share an edge) -> " << outPath << "\n";
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
  if (argc >= 3 && std::string(argv[1]) == "--make-test-nurbs") {
    return makeTestNurbs(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-bspline-edge") {
    return makeTestBsplineEdge(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-cylinder") {
    return makeTestCylinder(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-sphere") {
    return makeTestSphere(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-torus") {
    return makeTestTorus(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-mirror") {
    return makeTestMirror(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--make-test-nonmanifold") {
    return makeTestNonManifold(argv[2]);
  }
  if (argc >= 3 && std::string(argv[1]) == "--diagnose") {
    return diagnose(argv[2]);
  }
  if (argc < 2) {
    std::cerr << "usage: occ-debug-mesh [--timeout <sec>] <input.brep> [output.mesh.json]\n"
              << "       occ-debug-mesh --make-test-box <out.brep>\n"
              << "       occ-debug-mesh --make-test-bad <out.brep>\n";
    return 1;
  }
  // Optional mesh watchdog: --timeout <sec> before the input path (0/absent = off).
  // On expiry, unmeshed faces fall into failed_faces (partial=true), no crash (V2).
  double timeoutSec = 0.0;
  int argi = 1;
  if (std::string(argv[argi]) == "--timeout") {
    if (argi + 1 >= argc) {
      std::cerr << "[occ-debug-mesh] --timeout needs a value in seconds\n";
      return 1;
    }
    timeoutSec = std::atof(argv[argi + 1]);
    argi += 2;
  }
  if (argi >= argc || std::string(argv[argi]).rfind("--", 0) == 0) {  // unknown flag / no input (M3)
    std::cerr << "[occ-debug-mesh] unknown option or missing input: "
              << (argi < argc ? argv[argi] : "(none)") << "\n"
              << "usage: occ-debug-mesh [--timeout <sec>] <input.brep> [output.mesh.json]\n";
    return 1;
  }
  const std::string inPath = argv[argi];
  const std::string outPath = (argi + 1 < argc) ? argv[argi + 1] : (inPath + ".mesh.json");
  // Top-level safety net: any kernel exception that escapes convert() becomes a
  // clean error exit, never std::terminate (B1).
  try {
    return convert(inPath, outPath, timeoutSec);
  } catch (const Standard_Failure& e) {
    std::cerr << "[occ-debug-mesh] fatal: " << e.GetMessageString() << "\n";
    return 3;
  }
}

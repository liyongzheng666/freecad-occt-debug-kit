# =====================================================================
# occ-debug-mesh — BREP -> print-mesh (per-face world-coordinate triangles).
#
# Links the SAME local OCCT (occt/install/debug) the debugged process uses, so
# triangulation matches the captured BREP's kernel (M2-10 / linkage doc).
# Configure with -DOpenCASCADE_DIR pointing at the INSTALL tree
# occt/install/debug/lib/cmake/opencascade -- NOT the build tree occt/build/debug,
# whose config references unbuilt module Targets and fails (see README §2).
# =====================================================================
cmake_minimum_required(VERSION 3.16)
project(occ_debug_mesh LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(OpenCASCADE REQUIRED)

add_executable(occ-debug-mesh src/main.cxx)
target_include_directories(occ-debug-mesh PRIVATE ${OpenCASCADE_INCLUDE_DIR})
target_link_libraries(occ-debug-mesh PRIVATE
  TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep TKGeomAlgo TKTopAlgo TKMesh TKPrim)

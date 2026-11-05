"""Exact fixed-axis proof allowing duplicate vertices at export attribute seams."""
import numpy as np
from .l1_format_axes import prove_conversion, ROW_MATRIX
from .l1_surface import SurfaceMesh


def prove_split_vertex_conversion(native_vertices,native_triangles,export_vertices,export_triangles):
    populations=[]
    for vertices,triangles in ((native_vertices,native_triangles),(export_vertices,export_triangles)):
        # Exact equality only. No precision-grid weld, distance tolerance,
        # nearest-neighbor pairing, translation or optimized rotation.
        mesh=SurfaceMesh(vertices,triangles)
        unique,inverse=np.unique(mesh.vertices,axis=0,return_inverse=True)
        populations.append(SurfaceMesh(unique,inverse[mesh.triangles]))
    _,proof=prove_conversion(*populations)
    transformed=np.asarray(export_vertices,float)@np.asarray(ROW_MATRIX,float)
    return transformed,{**proof,'protocol':'continuous-exact-split-vertex-format-axes-v2',
        'vertex_seam_policy':'merge_exactly_identical_coordinates_for_geometry_proof_only',
        'original_native_vertices':len(native_vertices),'original_export_vertices':len(export_vertices),
        'unique_native_vertices':len(populations[0].vertices),'unique_export_vertices':len(populations[1].vertices),
        'original_export_topology_retained':True,'material_or_uv_equivalence_implied':False}

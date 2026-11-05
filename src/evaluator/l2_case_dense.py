"""Bounded dense-mesh facts: full geometry hashes/volume, explicitly sampled surfaces."""
import hashlib
import math
from pathlib import Path

EVIDENCE_DIRECTORY = None

import numpy as np
try:
    from .l2_mesh_order import indexed_surface_hash
except ImportError:  # Standalone, evaluator-owned Blender worker.
    from l2_mesh_order import indexed_surface_hash


def dense_facts(result,evaluated,mesh,scale):
    count=len(mesh.vertices);tri_count=len(mesh.loop_triangles)
    vertices=np.empty(count*3,dtype=np.float32);mesh.vertices.foreach_get('co',vertices)
    local=vertices.reshape((-1,3)).astype(np.float64)
    matrix=np.asarray(evaluated.matrix_world,dtype=np.float64)
    world=(local@matrix[:3,:3].T+matrix[:3,3])*scale
    if not np.isfinite(world).all():raise ValueError('Non-finite evaluated mesh coordinates')
    triangles=np.empty(tri_count*3,dtype=np.int32);mesh.loop_triangles.foreach_get('vertices',triangles)
    triangles=triangles.reshape((-1,3))
    hasher=hashlib.sha256();hasher.update(np.round(world,6).tobytes());hasher.update(triangles.tobytes())
    signed=0.;degenerate=0
    origin=world.mean(axis=0) if len(world) else np.zeros(3)
    for start in range(0,tri_count,20000):
        t=world[triangles[start:start+20000]]-origin
        cross=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0])
        degenerate+=int((np.linalg.norm(cross,axis=1)<=1e-18).sum())
        signed+=float(np.einsum('ij,ij->i',t[:,0],np.cross(t[:,1],t[:,2])).sum()/6)
    low,high=world.min(axis=0),world.max(axis=0)
    support=world[world[:,2]<=low[2]+.02];support=support[::max(1,math.ceil(len(support)/32))]
    step=max(1,math.ceil(tri_count/2000))
    sampled=world[triangles[::step]].tolist()
    result.update(vertices=count,edges=len(mesh.edges),faces=len(mesh.polygons),bounds=[low.tolist(),high.tolist()],
        dimensions=(high-low).tolist(),volume=abs(signed),components=None,nonmanifold_edges=None,
        degenerate_faces=degenerate,closed=False,polygon_count=len(mesh.polygons),support_points=support.tolist(),
        evaluated_geometry_sha256=hasher.hexdigest(),surface_triangles=sampled,
        surface_order_independent_sha256=indexed_surface_hash(world,triangles),
        geometry_evidence={'status':'sampled_surface','full_vertex_count':count,'full_triangle_count':tri_count,
            'surface_triangle_count':len(sampled),'geometry_hash':'full evaluated vertices and triangles',
            'topology_status':'not_measured','limitation':'Surface sampling is for bounded diagnostics, not complete intersection/support evidence.'})
    if EVIDENCE_DIRECTORY is not None:
        name='geometry-'+hashlib.sha256(evaluated.name.encode()).hexdigest()[:24]+'.npz'
        path=Path(EVIDENCE_DIRECTORY)/name
        np.savez(path,vertices=world,triangles=triangles)
        with path.open('rb') as stream:
            file_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        result['geometry_evidence'].update(full_geometry_file=name,full_geometry_sha256=file_sha)
    materials=[];properties=[];textures=0
    for material in mesh.materials:
        if material is None:continue
        materials.append(material.name)
        nodes=[n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED'] if material.use_nodes else []
        textures+=sum(n.type=='TEX_IMAGE' for n in material.node_tree.nodes) if material.use_nodes else 0
        properties.append({'principled':bool(nodes),'metallic':float(nodes[0].inputs['Metallic'].default_value) if nodes else float(material.metallic),
                           'roughness':float(nodes[0].inputs['Roughness'].default_value) if nodes else float(material.roughness)})
    result.update(materials=materials,image_texture_count=textures,material_properties=properties)
    return result

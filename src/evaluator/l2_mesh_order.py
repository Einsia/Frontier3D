"""Exact face-order invariance for seed reproduction, never a remeshing tolerance.

Vertex order/coordinates, oriented polygon cycles, corner UV/attributes, material
assignment, smoothing and edge/point attributes remain bound. Only polygon/edge
enumeration and cyclic starting corner are normalized.
"""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def cycle(corners):
    variants=[corners[i:]+corners[:i] for i in range(len(corners))]
    return min(variants,key=lambda v:json.dumps(v,sort_keys=True,separators=(',',':')))


def canonical_faces(faces):
    normalized=[{**face,'corners':cycle(face['corners'])} for face in faces]
    return sorted(normalized,key=lambda v:json.dumps(v,sort_keys=True,separators=(',',':')))


def surface_hash(surface):
    return digest(canonical_faces([{'corners':t} for t in surface]))


def indexed_surface_hash(vertices,triangles):
    """Bind every evaluated vertex and oriented triangle, never surface samples.

    Vertex indices remain fixed. Only triangle enumeration and cyclic corner
    origin are normalized; winding, duplicate faces and coordinates are bound.
    """
    import numpy as np
    vertices=np.asarray(vertices,dtype='<f8')
    triangles=np.asarray(triangles)
    if (vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all()
            or triangles.ndim!=2 or triangles.shape[1]!=3 or triangles.dtype.kind not in 'iu'
            or triangles.size and (triangles.min()<0 or triangles.max()>=len(vertices))):
        raise ValueError('Invalid complete evaluated geometry')
    triangles=triangles.astype('<i8')
    # Lexicographically smallest cyclic rotation also handles repeated indices.
    rotations=np.stack([np.roll(triangles,-i,axis=1) for i in range(3)],axis=1)
    choice=np.lexsort((rotations[:,:,2],rotations[:,:,1],rotations[:,:,0]),axis=1)[:,0]
    rows=rotations[np.arange(len(triangles)),choice]
    rows=rows[np.lexsort((rows[:,2],rows[:,1],rows[:,0]))]
    h=hashlib.sha256(b'l2-full-indexed-surface-v1\0')
    h.update(json.dumps([vertices.shape,rows.shape]).encode())
    h.update(vertices.tobytes());h.update(rows.tobytes())
    return h.hexdigest()


def native_hash(data,serialize):
    excluded={'position','.edge_verts','.corner_vert','.corner_edge'}
    attributes={domain:{} for domain in ('POINT','EDGE','FACE','CORNER')}
    metadata=[]
    for attr in data.attributes:
        if attr.name in excluded or attr.domain not in attributes:continue
        metadata.append((attr.name,attr.domain,attr.data_type))
        attributes[attr.domain][attr.name]=[serialize(v) for v in attr.data]
    def values(domain,index):
        return {name:entries[index] for name,entries in attributes[domain].items()}
    large=len(data.polygons)>20000
    # Keep old small-mesh signatures compatible. Dense meshes keep compact
    # per-element digests instead of a second full nested JSON copy.
    pack=digest if large else lambda value:value
    vertices=[pack({'co':list(v.co),'attributes':values('POINT',v.index)}) for v in data.vertices]
    edges=[pack({'vertices':sorted(e.vertices),'attributes':values('EDGE',e.index)}) for e in data.edges]
    faces=[]
    for polygon in data.polygons:
        corners=[{'vertex':data.loops[i].vertex_index,'attributes':values('CORNER',i),
            'uv':{layer.name:list(layer.data[i].uv) for layer in data.uv_layers}} for i in polygon.loop_indices]
        faces.append(pack({'corners':cycle(corners) if large else corners,'material_index':polygon.material_index,
            'use_smooth':polygon.use_smooth,'attributes':values('FACE',polygon.index)}))
    return digest({'vertices':vertices,'edges':sorted(edges,key=lambda e:json.dumps(e,sort_keys=True)),
        'faces':sorted(faces) if large else canonical_faces(faces),'attribute_schema':sorted(metadata),
        'uv_layers':[(layer.name,layer.active_render,layer.active_clone) for layer in data.uv_layers],
        'active_uv_layer':data.uv_layers.active_index})


def reproduction_fields(obj):
    native=obj.get('native_order_independent_sha256');surface=obj.get('surface_order_independent_sha256')
    if native and surface:
        return {'geometry_sha256':native,'evaluated_geometry_sha256':surface}
    return {key:obj.get(key) for key in ('geometry_sha256','evaluated_geometry_sha256')}

"""Geometry fixtures shared by L3 physical measurement regression controls."""
import hashlib
import numpy as np

def box(low, high):
    lo, hi = np.array(low,float), np.array(high,float)
    vertices = np.array([[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]])
    faces = [[0,2,3],[0,3,1],[4,5,7],[4,7,6],[0,1,5],[0,5,4],
             [2,6,7],[2,7,3],[0,4,6],[0,6,2],[1,3,7],[1,7,5]]
    return vertices[np.asarray(faces)]

def mesh(surface):
    return {'type':'MESH','visible_render':True,'bounds':[surface.min((0,1)).tolist(),surface.max((0,1)).tolist()],
            'surface_triangles':surface.tolist(),'evaluated_geometry_sha256':hashlib.sha256(surface.tobytes()).hexdigest()}

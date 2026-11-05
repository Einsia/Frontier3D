"""Build a portable fixture mesh solely from Text2Code 014's public numbers.

Run once with cadquery-ocp-novtk==7.9.3.1.1. The Blender entry needs only the
resulting bundled asset. No private reference or downloaded source mesh is read.
API: https://occt3d.com/dev/doc/refman/html/class_b_rep_offset_a_p_i___make_pipe_shell.html
"""
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.TColgp import TColgp_HArray1OfPnt
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

points = [(0, 0, 0), (0, 0, 10.348767), (11.4975, 0, 20.995524),
          (15.5835, 0, 21.221145), (16.821, 0, 42.57)]
array = TColgp_HArray1OfPnt(1, len(points))
for i, point in enumerate(points, 1):
    array.SetValue(i, gp_Pnt(*point))
interpolation = GeomAPI_Interpolate(array, False, 1e-6)
interpolation.Perform()
assert interpolation.IsDone()
path = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(interpolation.Curve()).Edge()).Wire()
polygon = BRepBuilderAPI_MakePolygon()
for x, y in [(-4.65, -3.45), (4.65, -3.45), (4.65, 3.45), (-4.65, 3.45)]:
    polygon.Add(gp_Pnt(x, y, 0))
polygon.Close()
pipe = BRepOffsetAPI_MakePipeShell(path)
pipe.SetMode(False)  # Corrected Frenet, with no extra twist or endpoint tangents.
pipe.Add(polygon.Wire(), False, False)
pipe.Build()
assert pipe.IsDone() and pipe.MakeSolid()
shape = pipe.Shape()
assert BRepCheck_Analyzer(shape).IsValid()
properties = GProp_GProps()
BRepGProp.VolumeProperties_s(shape, properties)
assert properties.Mass() > 0
BRepMesh_IncrementalMesh(shape, .01, False, .1, False).Perform()
vertices, faces, lookup = [], [], {}
explorer = TopExp_Explorer(shape, TopAbs_FACE)
while explorer.More():
    face = TopoDS.Face_s(explorer.Current())
    location = TopLoc_Location()
    triangles = BRep_Tool.Triangulation_s(face, location)
    indices = {}
    for i in range(1, triangles.NbNodes() + 1):
        p = triangles.Node(i).Transformed(location.Transformation())
        key = tuple(round(v, 8) for v in (p.X(), p.Y(), p.Z()))
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append([v / 1000 for v in key])
        indices[i] = lookup[key]
    for i in range(1, triangles.NbTriangles() + 1):
        a, b, c = triangles.Triangle(i).Get()
        if face.Orientation() == TopAbs_REVERSED:
            b, c = c, b
        faces.append([indices[a], indices[b], indices[c]])
    explorer.Next()
root = Path(__file__).resolve().parent
asset = root / 'assets' / 'public_sweep.json'
asset.parent.mkdir(exist_ok=True)
asset.write_text(json.dumps({'units': 'metres', 'vertices': vertices, 'faces': faces}))
metadata = {'source': 'public instruction coordinates only; no GT or source model',
            'builder_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'cadquery_ocp_novtk': version('cadquery-ocp-novtk'), 'valid_solid': True,
            'volume_mm3': properties.Mass(), 'linear_deflection_mm': .01,
            'vertices': len(vertices), 'triangles': len(faces),
            'asset_sha256': hashlib.sha256(asset.read_bytes()).hexdigest()}
(root / 'assets' / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
print(json.dumps(metadata))

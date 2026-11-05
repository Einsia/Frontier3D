"""Verify saved L1 meshes against an independent analytic CSG oracle."""
import bpy,sys,json,random
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from geometry_checks import analytic_inside

def tree():
    verts=[];polys=[]
    for o in bpy.context.scene.objects:
        if o.type!='MESH':continue
        offset=len(verts);verts.extend(o.matrix_world@v.co for v in o.data.vertices)
        polys.extend([offset+i for i in p.vertices] for p in o.data.polygons)
    return BVHTree.FromPolygons(verts,polys)

def mesh_inside(bvh,point):
    p=Vector(point);direction=Vector((1,.000013,.000019)).normalized();hits=0
    for _ in range(100):
        loc,normal,index,dist=bvh.ray_cast(p,direction,2)
        if loc is None:break
        hits+=1;p=loc+direction*1e-7
    return hits%2==1

def main():
    reports=[]
    for path in sorted((ROOT/'pilot/tasks').glob('L1-*')):
        spec=json.loads((path/'author/target.json').read_text(encoding='utf-8'))
        bpy.ops.wm.open_mainfile(filepath=str(path/'reference/scene.blend'),load_ui=False)
        bvh=tree();rng=random.Random(20260911)
        geometry=json.loads((path/'reference/geometry.json').read_text())['Body'];lo,hi=geometry['bounds']
        points=[[rng.uniform(lo[k]-.001,hi[k]+.001) for k in range(3)] for _ in range(1024)]
        anchors=[dict(point=p,inside=analytic_inside(p,spec)) for p in points]
        mismatch=sum(mesh_inside(bvh,p['point'])!=p['inside'] for p in anchors)
        report=dict(task=path.name,queries=len(points),mismatches=mismatch,passed=mismatch<=4)
        (path/'author/occupancy_tests.json').write_text(json.dumps(anchors,indent=2),encoding='utf-8')
        reports.append(report);print('CSG_CHECK',report,flush=True)
    (ROOT/'pilot/qa/csg.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in reports):raise RuntimeError('Analytic geometry mismatch')

if __name__=='__main__':main()

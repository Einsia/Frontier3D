"""Render separate-part assemblies, exploded views, and independently inspect parts."""
import bpy,sys,json,math,random
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from assembly_catalog import assemblies
from blender_backend import reset,build_csg,material,geometry_report
from geometry_checks import analytic_inside
from check_csg_blender import mesh_inside

def construct(spec,explode=False,defect=False):
    reset()
    root=bpy.data.objects.new('Assembly',None);bpy.context.collection.objects.link(root)
    for i,p in enumerate(spec['parts']):
        obj=build_csg(dict(family=spec['family'],operations=p['operations']))
        obj.name=p['id'];obj.data.materials.clear();obj.data.materials.append(material(p['id'],p['color']))
        obj.location=Vector(p['at'])*.001
        if explode:obj.location+=Vector(p['explode'])*.001
        if defect and i==2:obj.location.x+=.006;obj.rotation_euler.z=math.radians(12)
        obj.parent=root;obj['part_id']=p['id']
    bpy.context.view_layer.update()

def camera_setup():
    scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL';scene.display.shading.show_cavity=True;scene.display.shading.cavity_type='BOTH'
    scene.render.resolution_x=960;scene.render.resolution_y=720;scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    scene.world=bpy.data.worlds.new('World');scene.world.color=(.085,.10,.13);scene.display.shading.background_type='WORLD'
    bpy.ops.object.camera_add();cam=bpy.context.object;cam.name='AssemblyCamera';cam.data.type='ORTHO';cam.data.clip_start=.0001;scene.camera=cam
    return scene,cam

def render(scene,cam,path,direction=(1.4,-1.8,1.2)):
    points=[o.matrix_world@Vector(c) for o in scene.objects if o.type=='MESH' for c in o.bound_box]
    low=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);center=(low+hi)/2;span=max(hi-low)
    cam.location=center+Vector(direction)*span;cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=span*1.65
    scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)

def inspect(spec):
    reports=[];anchors={};rng=random.Random(42)
    geometry=geometry_report()
    for p in spec['parts']:
        obj=bpy.data.objects[p['id']];co=[obj.matrix_world@v.co for v in obj.data.vertices]
        tree=BVHTree.FromPolygons(co,[list(f.vertices) for f in obj.data.polygons])
        lo,hi=geometry[p['id']]['bounds'];queries=[];mismatches=0
        for _ in range(512):
            point=[rng.uniform(lo[k]-.001,hi[k]+.001) for k in range(3)]
            local=[point[k]-p['at'][k]*.001 for k in range(3)]
            expected=analytic_inside(local,p);actual=mesh_inside(tree,point)
            queries.append(dict(point=point,inside=expected));mismatches+=actual!=expected
        g=geometry[p['id']]
        reports.append(dict(part=p['id'],passed=g['nonmanifold_edges']==0 and g['components']==1 and g['volume']>0 and mismatches<=4,components=g['components'],nonmanifold_edges=g['nonmanifold_edges'],mismatches=mismatches))
        anchors[p['id']]=queries
    return geometry,reports,anchors

def build(spec):
    folder=ROOT/'pilot-v2/assemblies'/spec['family'];folder.mkdir(parents=True,exist_ok=True)
    construct(spec);scene,cam=camera_setup();geometry,checks,anchors=inspect(spec)
    for name,value in [('spec.json',spec),('geometry.json',geometry),('qa.json',checks),('occupancy_tests.json',anchors)]:
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    render(scene,cam,folder/'assembled.png');render(scene,cam,folder/'front.png',(0,-2,.01));render(scene,cam,folder/'top.png',(0,0,2))
    # Native assembly retains independently editable meshes and a reversible exploded state.
    for p in spec['parts']:
        o=bpy.data.objects[p['id']];o.location=Vector(p['at'])*.001;o.keyframe_insert('location',frame=1)
        o.location=(Vector(p['at'])+Vector(p['explode']))*.001;o.keyframe_insert('location',frame=61)
    scene.frame_end=61;scene.frame_set(61);render(scene,cam,folder/'exploded.png')
    scene.frame_set(1);render(scene,cam,folder/'assembled.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'scene.blend'),compress=True)
    bpy.ops.export_scene.gltf(filepath=str(folder/'scene.glb'),export_format='GLB',export_animations=False)
    # Initial edit state has a known positional/orientation fault in a named part.
    faulty=bpy.data.objects[spec['parts'][2]['id']];faulty.animation_data_clear();faulty.location.x+=.006;faulty.rotation_euler.z=math.radians(12)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder/'initial.blend'),compress=True)
    print('ASSEMBLY_DONE',spec['family'],len(spec['parts']),all(r['passed'] for r in checks),[r for r in checks if not r['passed']],flush=True)

if __name__=='__main__':
    requested=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    for spec in assemblies():
        if not requested or spec['family'] in requested:build(spec)

"""Public-number control scene. NOT a text-to-scene answer or a model result."""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

NUMBER=__CASE__
MODE='__MODE__'
p=argparse.ArgumentParser();p.add_argument('--input-dir');p.add_argument('--output-dir',type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);scene=bpy.context.scene
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
scene.render.engine='CYCLES';scene.cycles.samples=2;scene.cycles.use_denoising=False;scene.cycles.seed=0
scene.render.resolution_x,scene.render.resolution_y=(960,640) if NUMBER==8 else (1280,960) if NUMBER==10 else (1200,1000)
scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
scene.view_settings.view_transform='AgX';scene.view_settings.look='AgX - Medium High Contrast'
scene.view_settings.exposure=0;scene.view_settings.gamma=1
roles={};materials={};serial=0


def material(role):
    if role not in materials:
        m=bpy.data.materials.new('material_'+str(len(materials)));m.use_nodes=True
        color=(.22,.38,.26,1) if role in {'site','island','tree','lane'} else (.42,.3,.18,1)
        m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=color;materials[role]=m
    return materials[role]


def register(obj,role,parent=None):
    global serial
    obj.name='numeric_piece_'+str(serial);serial+=1;obj['bench_role']=role
    if parent:obj.parent=parent
    obj.data.materials.append(material(role));roles.setdefault(role,[]).append(obj)
    return obj


def parent(role):
    obj=bpy.data.objects.new('group_'+str(len(bpy.data.objects)),None);scene.collection.objects.link(obj);obj['bench_role']=role
    return obj


def box(role,position,dimensions,owner=None):
    bpy.ops.mesh.primitive_cube_add(size=1,location=position);obj=bpy.context.object;obj.dimensions=dimensions
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return register(obj,role,owner)


def sphere(role,position,diameter):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=diameter/2,location=position)
    return register(bpy.context.object,role)


def site(x,y,role='site'):return box(role,(0,0,-.1),(x,y,.2))


def patch(role,x,y,z=0):return box(role,(x,y,z+.0001),(.04,.04,.0002))


def path(role,width,length,start,goal,x=0,y=0):
    box(role,(x,y,-.015),(width,length,.03))
    # This fixture nominates interior staging patches. The conservative route
    # probe needs a full clearance disk around each center, including its ends.
    inset=max(1,width/2+.2)
    patch(start,x,y-length/2+inset);patch(goal,x,y+length/2-inset)


def items(role,count,x=9,y=-9,spacing=2,dimensions=(.5,.5,1)):
    for i in range(count):box(role,(x+(i%2)*spacing,y+(i//2)*spacing,dimensions[2]/2),dimensions)


def gateway(role,width,height,x=0,y=0):
    root=parent(role);thickness=.2
    box(role,(x-width/2-thickness/2,y,(height+thickness)/2),(thickness,.4,height+thickness),root)
    box(role,(x+width/2+thickness/2,y,(height+thickness)/2),(thickness,.4,height+thickness),root)
    box(role,(x,y,height+thickness/2),(width+2*thickness,.4,thickness),root)


if NUMBER==1:
    site(34,32);box('water',(-10,0,-.025),(12,30,.05))
    box('ship_hull',(-10,0,.25),(3,8,1.5));box('ship_deck',(-10,0,1.05),(2.8,7,.1))
    items('rowing_boat',1,-7,-9,dimensions=(1,2,.5));items('mast',2,-10,-2,spacing=3,dimensions=(.2,.2,4))
    items('hut_support',4,9,6,dimensions=(.2,.2,2));items('palm',4,11,-7)
    items('barrel',5,7,-8,spacing=1);items('crate',5,7,-3,spacing=1)
    path('pier',1.6,22,'shore','docking_end')
elif NUMBER==2:
    site(36,32);items('rover',3,7,-8,dimensions=(1.2,2,1))
    items('rocket',1,12,8,dimensions=(1,1,4));items('tank_section',2,12,2,dimensions=(1,1,1))
    box('rail',(-10,0,2.7),(.8,20,.1));items('rail_vehicle',1,-10,-2,dimensions=(.6,1,1))
    for y in (-8,-5,-2,2,5,8):box('rail_support',(-10,y,1.3),(.25,.25,2.6))
    items('crater',4,7,7,dimensions=(1.5,1.5,.1))
    path('apron',2.5,26,'hangar_entry','apron_edge')
elif NUMBER==3:
    site(32,34);path('road',6,30,'road_start','road_end')
    for side,x in [('left',-4),('right',4)]:path('sidewalk_'+side,1.6,30,'sidewalk_'+side+'_start','sidewalk_'+side+'_end',x=x)
    for x in (-9,9):
        for y in (-10,0,10):box('house',(x,y,2),(4,4,4))
    for x in (-14,14):
        for y in (-12,-8,-4,4,8,12):box('tree',(x,y,1.5),(.7,.7,3))
    for x in (-6,6):
        for y in (-10,0,10):box('planter',(x,y,.3),(.5,.5,.6))
elif NUMBER==4:
    site(29,28);box('courtyard',(0,0,-.005),(18,18,.01))
    for x in (-10,10):
        for y in (-10,10):box('corner_tower',(x,y,3),(2,2,6))
    gateway('gateway',2.4,2.8,y=-10)
    path('entry_route',2.4,14,'bridge_start','courtyard_goal',y=-6)
elif NUMBER==5:
    site(24,24);path('path',2.5,22,'entrance','crypt_entry')
    for side in (-1,1):
        for y in (-6,0,6):
            for x in (4,7):
                root=parent('grave');box('grave',(side*x,y,.1),(1.1,2,.2),root)
                box('grave',(side*x,y+.8,.6),(.7,.1,1.2),root)
    for x in (-10,10):
        for y in (-10,10):box('tree',(x,y,1.5),(.8,.8,3))
    for y in (-7,0,7):box('light_post',(2,y,1.5),(.2,.2,3))
elif NUMBER==6:
    site(25,26)
    for x in (-7,0,7):
        box('lane',(x,0,-.05),(4,20,.1));sphere('ball',(x,-8.8,.05),.1)
        box('cup',(x,8,-.07),(.2,.2,.1));box('diamond_obstacle',(x+.8,6,.1),(.4,.4,.2))
        box('visitor_path',(x,-10.4,-.015),(1.6,2,.03));patch('lane_start',x,-10.1)
    box('visitor_path',(0,-11.4,-.015),(22,1.6,.03));patch('visitor_entry',0,-11.4)
    gateway('windmill',.5,.5,x=-7);gateway('castle_arch',.5,.5)
elif NUMBER==7:
    site(40,40,'island');box('tower',(0,0,15),(3,3,30));items('tree',6,7,-7,dimensions=(1,1,4))
elif NUMBER==8:
    site(36,60);path('passage',3.6,56,'foreground_entry','far_exit')
    items('rock_mass',3,-12,-15,spacing=7,dimensions=(3,4,12));items('pillar',2,9,-6,spacing=5,dimensions=(2,2,10))
    items('vegetation_cluster',3,11,7,spacing=4,dimensions=(1,1,2));gateway('natural_arch',6.5,7)
elif NUMBER==9:
    site(80,80);items('crater',3,-10,3,spacing=6,dimensions=(3,3,.15))
    for i,size in enumerate((.05,.2,.5,1.)):sphere('rock',(-4+i*3,-12,size*.4),size)
elif NUMBER==10:
    site(40,30);path('road',4.6,26,'entrance','work_zone')
    box('mixer_truck',(-8,0,1),(2,4,2));box('dump_truck',(8,0,1),(2,4,2))

# Each mutation violates a public numerical requirement, rather than changing a
# semantic/style judgment or copying a reference picture.
count_role={1:'ship_hull',2:'rover',3:'house',4:'corner_tower',5:'grave',6:'lane',7:'tree',8:'pillar',9:'crater',10:'mixer_truck'}[NUMBER]
if MODE=='wrong_count':
    obj=roles[count_role][0];group=obj.parent
    victims=list(group.children) if group else [obj]
    for victim in victims:bpy.data.objects.remove(victim,do_unlink=True)
    if group:bpy.data.objects.remove(group,do_unlink=True)
if MODE=='wrong_scale':
    for obj in roles['island' if NUMBER==7 else 'site']:obj.scale.x*=.5;obj.scale.y*=.5
if MODE=='blocked_route':
    role={1:'pier',2:'apron',3:'road',4:'entry_route',5:'path',6:'visitor_path',8:'passage',10:'road'}[NUMBER]
    point=(0,-10,0) if NUMBER==4 else (0,-11.4,0) if NUMBER==6 else (0,0,0)
    box('deliberate_barrier',(point[0],point[1],.04),(30,.1,.08))

bpy.ops.object.light_add(type='SUN',location=(5,-10,20));bpy.context.object.data.energy=2
bpy.context.object.rotation_euler=(.3,-.4,-.3)
cameras=[]
if NUMBER==8:
    positions=[(0,-25,1.7),(15,-20,10)];targets=[(0,5,5),(0,0,2)]
elif NUMBER==9:
    positions=[(0,-28,1.6),(2,-28,1.6)];targets=[(0,0,2),(2,0,2)]
else:
    radius=60 if NUMBER==7 else 45;elevation=60 if NUMBER==10 else 45
    positions=[(radius*math.cos(math.radians(angle)),radius*math.sin(math.radians(angle)),radius*math.tan(math.radians(elevation))) for angle in (25,50)]
    targets=[(0,0,0),(0,0,0)]
for i,(position,target) in enumerate(zip(positions,targets)):
    data=bpy.data.cameras.new('view_'+str(i));obj=bpy.data.objects.new('view_'+str(i),data);scene.collection.objects.link(obj)
    obj.location=position;obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
    if NUMBER not in (8,9):data.type='ORTHO';data.ortho_scale=80 if NUMBER==7 else 65
    cameras.append(obj)
for camera,name in zip(cameras,('main.png','alternate.png')):
    scene.camera=camera;scene.render.filepath=str(a.output_dir/name);bpy.ops.render.render(write_still=True)
scene.camera=cameras[0];bpy.ops.wm.save_as_mainfile(filepath=str(a.output_dir/'scene.blend'))

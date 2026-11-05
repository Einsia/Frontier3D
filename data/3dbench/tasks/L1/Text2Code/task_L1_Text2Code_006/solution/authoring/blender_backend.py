"""Blender 5.2 reference authoring backend; deterministic SI output."""
import bpy, bmesh, math, json, sys, hashlib
from pathlib import Path
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[1]

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system='METRIC'
    bpy.context.scene.unit_settings.scale_length=1

def material(name, color):
    name=name+'_'+''.join(f'{round(v*255):02x}' for v in color)
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color=(*color,1)
    m.use_nodes=True
    m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(*color,1)
    m.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value=.65
    return m

def primitive(op):
    p=op.get('at',[0,0,0]); shape=op['shape']
    if shape=='box':
        bpy.ops.mesh.primitive_cube_add(size=1, location=p)
        bpy.context.object.dimensions=op['size']
    else:
        bpy.ops.mesh.primitive_cone_add(vertices=op.get('vertices',96),radius1=op['radius'],
            radius2=op.get('radius_top',op['radius']),depth=op['height'],location=p)
    obj=bpy.context.object
    if op.get('axis')=='x':obj.rotation_euler.y=math.pi/2
    if op.get('axis')=='y':obj.rotation_euler.x=math.pi/2
    obj.rotation_euler.z=math.radians(op.get('rotation_z',0))
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return obj

def build_csg(spec):
    body=None
    for i,op in enumerate(spec['operations']):
        tool=primitive(op)
        if body is None:
            body=tool;continue
        bpy.context.view_layer.objects.active=body
        mod=body.modifiers.new('feature_%02d'%i,'BOOLEAN')
        mod.operation=op.get('op','union').upper();mod.solver='EXACT';mod.object=tool
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(tool,do_unlink=True)
    body.name='Body'
    # Bake world placement and convert the authoring millimetres to metres.
    world=body.matrix_world.copy()
    for v in body.data.vertices:v.co=world@v.co*.001
    body.matrix_world.identity()
    body.data.materials.clear();body.data.materials.append(material('Anodized blue',(.14,.43,.62)))
    body['family']=spec['family'];body['units']='metres'
    bpy.context.view_layer.update()
    return body

def import_asset(item):
    before=set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT/item['asset']))
    added=set(bpy.data.objects)-before
    meshes=sorted((o for o in added if o.type=='MESH'),key=lambda o:o.name)
    nonmeshes=[o for o in added if o.type!='MESH']
    if not meshes:raise ValueError('No meshes: '+item['asset'])
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        matrix=o.matrix_world.copy();o.parent=None;o.matrix_world=matrix;o.select_set(True)
    bpy.context.view_layer.objects.active=meshes[0]
    bpy.ops.object.join();obj=bpy.context.object
    for o in nonmeshes:
        if o.name in bpy.data.objects:bpy.data.objects.remove(o,do_unlink=True)
    world=obj.matrix_world.copy()
    coords=[world@v.co for v in obj.data.vertices]
    low=Vector([min(v[a] for v in coords) for a in range(3)])
    high=Vector([max(v[a] for v in coords) for a in range(3)])
    dims=high-low;center=(high+low)/2
    for v,c in zip(obj.data.vertices,coords):
        v.co=Vector([(c[a]-(low[a] if a==2 else center[a]))*item['size'][a]/max(dims[a],1e-8) for a in range(3)])
    obj.matrix_world.identity()
    obj.location=item['at'];obj.rotation_euler.z=math.radians(item.get('yaw',0))
    obj.name=item['id'];return obj

def build_scene(spec):
    zones={}
    for name in spec.get('zones',['world']):
        o=bpy.data.objects.new('zone_'+name,None);bpy.context.collection.objects.link(o);zones[name]=o
    for item in spec['objects']:
        if item.get('asset'):obj=import_asset(item)
        else:
            at=item['at'];size=item['size']
            obj=primitive(dict(shape='box',size=size,at=[at[0],at[1],at[2]+size[2]/2]))
            obj.name=item['id'];obj.rotation_euler.z=math.radians(item.get('yaw',0))
            obj.data.materials.append(material(item.get('material','neutral'),item.get('color',[.55,.58,.6])))
        parent=zones[item.get('zone',next(iter(zones)))]
        bpy.context.view_layer.update()
        matrix=obj.matrix_world.copy();obj.parent=parent;obj.matrix_world=matrix
        obj['semantic_id']=item['id'];obj['category']=item.get('category','structure')
        obj['source_asset']=item.get('asset','original-procedural')
    bpy.context.view_layer.update()

def geometry_report():
    out={}
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH':continue
        mesh=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        co=[obj.matrix_world@v.co for v in mesh.vertices]
        if not co:raise ValueError('Empty mesh: '+obj.name)
        low=[min(v[i] for v in co) for i in range(3)];high=[max(v[i] for v in co) for i in range(3)]
        bm=bmesh.new();bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table();remaining=set(bm.verts);components=0
        while remaining:
            stack=[remaining.pop()];components+=1
            while stack:
                v=stack.pop()
                for e in v.link_edges:
                    w=e.other_vert(v)
                    if w in remaining:remaining.remove(w);stack.append(w)
        digest=hashlib.sha256()
        for v in co:digest.update((','.join(f'{x:.8f}' for x in v)+';').encode())
        for p in mesh.polygons:digest.update(str(tuple(p.vertices)).encode())
        out[obj.name]=dict(bounds=[low,high],dimensions=[high[i]-low[i] for i in range(3)],
            vertices=len(mesh.vertices),faces=len(mesh.polygons),nonmanifold_edges=sum(not e.is_manifold for e in bm.edges),
            components=components,volume=abs(bm.calc_volume()),geometry_sha256=digest.hexdigest(),
            parent=obj.parent.name if obj.parent else None,
            material_colors=[list(m.diffuse_color[:3]) for m in mesh.materials if m],
            material_signature=hashlib.sha256(json.dumps([
                {'color':list(m.diffuse_color),'images':sorted(hashlib.sha256(bytes(n.image.packed_file.data)).hexdigest() if n.image.packed_file else n.image.name.split('.')[0] for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image)}
                for m in mesh.materials if m and m.use_nodes],sort_keys=True).encode()).hexdigest())
        bm.free();obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    return out

def save_outputs(dest,spec,render=True):
    dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=True)
    report=geometry_report()
    (dest/'geometry.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box]
    low=Vector([min(v[i] for v in points) for i in range(3)])
    high=Vector([max(v[i] for v in points) for i in range(3)])
    center=(high+low)/2;span=max(high-low)
    scene=bpy.context.scene
    scene.render.engine='BLENDER_WORKBENCH'
    scene.display.shading.light='STUDIO';scene.display.shading.color_type='MATERIAL'
    scene.display.shading.show_shadows=True;scene.display.shading.show_cavity=True
    scene.display.shading.cavity_type='BOTH';scene.display.shading.show_specular_highlight=True
    scene.display.shading.background_type='WORLD';scene.world=bpy.data.worlds.new('Background')
    scene.world.color=(.085,.095,.12)
    scene.render.resolution_x=640;scene.render.resolution_y=640;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    bpy.ops.object.camera_add();camera=bpy.context.object;camera.name='ReviewCamera';scene.camera=camera
    camera.data.type='ORTHO';camera.data.ortho_scale=span*1.65
    camera.data.clip_start=max(.0001,span/1000);camera.data.clip_end=span*100
    angles={'iso':(1.3,-1.8,1.3),'front':(0,-2,0),'back':(0,2,0),'top':(0,0,2)} if spec['level']==1 else {'iso':(1.2,-1.7,1.8),'top':(0,0,2)}
    for view,direction in angles.items():
        camera.location=center+Vector(direction)*span
        camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        if render:
            scene.render.filepath=str(dest/(view+'.png'));bpy.ops.render.render(write_still=True)
    camera.location=center+Vector(angles['iso'])*span
    camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
    if spec['level']==1 and render:
        # Destructive-looking cutaway is made on a disposable copy, never on the reference body.
        original=bpy.data.objects['Body'];section=original.copy();section.data=original.data.copy()
        bpy.context.collection.objects.link(section);section.name='SectionPreview';original.hide_render=True
        cutter=primitive(dict(shape='box',size=[span*3,span*4,span*4],at=[span*1.5,0,center.z]))
        bpy.context.view_layer.objects.active=section
        modifier=section.modifiers.new('X_positive_cutaway','BOOLEAN');modifier.operation='DIFFERENCE';modifier.solver='EXACT';modifier.object=cutter
        bpy.ops.object.modifier_apply(modifier=modifier.name);bpy.data.objects.remove(cutter,do_unlink=True)
        scene.render.filepath=str(dest/'section.png');bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(section,do_unlink=True);original.hide_render=False
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(dest/'scene.blend'),compress=True)
    bpy.ops.export_scene.gltf(filepath=str(dest/'scene.glb'),export_format='GLB',export_cameras=False,export_lights=False)
    return report

def build(spec,dest,render=True):
    reset()
    if spec['level']==1:build_csg(spec)
    else:build_scene(spec)
    return save_outputs(dest,spec,render)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('spec');p.add_argument('output');p.add_argument('--no-render',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    build(json.loads(Path(a.spec).read_text(encoding='utf-8')),a.output,not a.no_render)

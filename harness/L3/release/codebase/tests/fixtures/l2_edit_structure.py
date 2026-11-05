"""Blender fixture mutation, injected after evaluator-owned target restoration."""
if mode in {'front_sheet','sealed_cavity','filled_cavity','bottomless_cavity'}:
 import bmesh
 from mathutils import Vector
 # Bake only new target meshes, retaining world transforms and material slots.
 depsgraph=bpy.context.evaluated_depsgraph_get()
 baked=[(o,o.matrix_world.copy(),bpy.data.meshes.new_from_object(o.evaluated_get(depsgraph),
         preserve_all_data_layers=True,depsgraph=depsgraph)) for o in added if o.type in {'MESH','CURVE'}]
 for o,matrix,mesh in baked:
  o.parent=None;o.constraints.clear();o.modifiers.clear()
  if o.type!='MESH':
   replacement=bpy.data.objects.new(o.name+'_mesh',mesh);s.collection.objects.link(replacement)
   bpy.data.objects.remove(o,do_unlink=True);o=replacement
  else:o.data=mesh
  o.matrix_world=matrix
 meshes=[o for o in s.objects if o.type=='MESH' and o.name.startswith('arbitrary_added_')]
 positions=[o.matrix_world@v.co for o in meshes for v in o.data.vertices]
 low=Vector(tuple(min(p[i] for p in positions) for i in range(3)))
 high=Vector(tuple(max(p[i] for p in positions) for i in range(3)))
 center=(low+high)/2;half=(high-low)/2
 if mode in {'sealed_cavity','filled_cavity'}:
  thickness=max(.002,(high.z-low.z)*.01)
  lower=high.z-thickness if mode=='sealed_cavity' else low.z
  bpy.ops.mesh.primitive_cube_add(size=1,location=(center.x,center.y,(lower+high.z)/2))
  block=bpy.context.object;block.name='cavity_obstruction'
  block.dimensions=(half.x*1.5,half.y*1.5,high.z-lower)
 elif mode in {'front_sheet','bottomless_cavity'}:
  for o in meshes:
   bm=bmesh.new();bm.from_mesh(o.data);bm.normal_update();remove=[]
   normal_matrix=o.matrix_world.to_3x3().inverted().transposed()
   for face in bm.faces:
    world=o.matrix_world@face.calc_center_median()
    if mode=='front_sheet':
     toward=s.camera.matrix_world.to_3x3()@Vector((0,0,1)) if s.camera.data.type=='ORTHO' else s.camera.matrix_world.translation-world
     discard=(normal_matrix@face.normal).dot(toward)<=1e-8
    else:discard=abs(world.x-center.x)<half.x*.65 and abs(world.y-center.y)<half.y*.65
    if discard:remove.append(face)
   bmesh.ops.delete(bm,geom=remove,context='FACES');bm.to_mesh(o.data);bm.free();o.data.update()
 bpy.context.view_layer.update()

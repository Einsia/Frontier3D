# Inserted after private control loading, before camera creation and rendering.
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
import bmesh

mutation=c['regional_control']['mutation']
if mutation=='join':
 bpy.ops.object.select_all(action='DESELECT')
 meshes=[obj for obj in added if obj.type=='MESH']
 matrices={obj:obj.matrix_world.copy() for obj in meshes}
 for obj in meshes:obj.parent=None;obj.matrix_world=matrices[obj];obj.select_set(True)
 bpy.context.view_layer.objects.active=meshes[0];bpy.ops.object.join()
elif mutation in {'omit','depth'}:
 selected=[s.objects['arbitrary_added_'+str(i)] for i in c['region_indices']]
 box=c.get('region_image_box')
 for obj in selected:
  if box:
   # The telescope is one mesh; materialize its evaluated geometry before
   # deleting/offsetting only the publicly described image-region vertices.
   evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
   mesh=bpy.data.meshes.new_from_object(evaluated)
   obj.modifiers.clear();obj.data=mesh
   chosen=[]
   for vertex in obj.data.vertices:
    q=world_to_camera_view(s,s.camera,obj.matrix_world@vertex.co)
    if q.z>0 and box[0]<=q.x<=box[2] and box[1]<=1-q.y<=box[3]:chosen.append(vertex.index)
   if not chosen:raise ValueError('Control image box selected no actual vertices')
   if mutation=='omit':
    bm=bmesh.new();bm.from_mesh(obj.data);bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm,geom=[bm.verts[i] for i in chosen],context='VERTS');bm.to_mesh(obj.data);bm.free()
   else:
    points=[obj.matrix_world@obj.data.vertices[i].co for i in chosen]
    low=Vector(tuple(min(p[i] for p in points) for i in range(3)));high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    offset=s.camera.matrix_world.to_3x3()@Vector((0,0,-.2*(high-low).length))
    local=obj.matrix_world.inverted().to_3x3()@offset
    for i in chosen:obj.data.vertices[i].co+=local
  elif mutation=='omit':bpy.data.objects.remove(obj,do_unlink=True)
  else:
   points=[obj.matrix_world@Vector(corner) for corner in obj.bound_box]
   low=Vector(tuple(min(p[i] for p in points) for i in range(3)));high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
   offset=s.camera.matrix_world.to_3x3()@Vector((0,0,-.2*(high-low).length))
   matrix=obj.matrix_world.copy();matrix.translation+=offset;obj.matrix_world=matrix
 bpy.context.view_layer.update()

"""Inserted into the evaluator-owned control after its private objects load."""
if mode in {'missing_hidden_container','ring_proxy','hidden_radius_variation','bevelled_box_proxy'}:
 from mathutils import Vector
 obj=s.objects['arbitrary_added_'+str(c['hidden_container_index'])]
 points=[obj.matrix_world@Vector(corner) for corner in obj.bound_box]
 low=Vector(tuple(min(p[i] for p in points) for i in range(3)))
 high=Vector(tuple(max(p[i] for p in points) for i in range(3)))
 center=(low+high)/2
 if mode=='hidden_radius_variation':
  # A plausible different hidden radius must not be forced to the private one.
  transform=Matrix.Diagonal((.85,.85,1.,1.))
  obj.matrix_world=Matrix.Translation(center)@transform@Matrix.Translation(-center)@obj.matrix_world
 else:
  material=obj.data.materials[0] if obj.data.materials else None
  bpy.data.objects.remove(obj,do_unlink=True)
  if mode=='ring_proxy':
   bpy.ops.mesh.primitive_torus_add(major_radius=.18,minor_radius=.006,major_segments=32,minor_segments=8,
                                  location=(center.x,center.y,low.z+.006))
   proxy=bpy.context.object;proxy.name='third_container_label_is_not_evidence'
   proxy['bench_role']='container'
   if material:proxy.data.materials.append(material)
  elif mode=='bevelled_box_proxy':
   bpy.ops.mesh.primitive_cube_add(size=1,location=center)
   proxy=bpy.context.object;proxy.name='bevelled_square_column'
   proxy.dimensions=(.32,.32,float(high.z-low.z))
   bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
   bevel=proxy.modifiers.new('Edge_bevel','BEVEL');bevel.width=.02;bevel.segments=1
   if material:proxy.data.materials.append(material)
 bpy.context.view_layer.update()

"""Actual start access controls; independent tags do not determine endpoints."""
if NUMBER==6:
    for obj in roles['visitor_path'][:3]:
        obj.location.y=-10.7;obj.scale.y=.7
    if MODE=='visitor_gap':
        obj=roles['visitor_path'][0];obj.location.y=-11.05;obj.scale.y=.35
    elif MODE=='visitor_step':roles['visitor_path'][0].location.z+=.3
    elif MODE=='visitor_blocked':box('visitor_barrier',(-7,-10.3,.15),(1.8,.04,.3))
    elif MODE=='visitor_inside_course':box('visitor_path',(-7,-7.5,-.015),(1.6,2,.03))
    elif MODE in {'displaced_visitor','visitor_role_spoof'}:
        for role in ('visitor_path','lane_start','visitor_entry'):
            for obj in roles[role]:obj.location.y-=2
        if MODE=='visitor_role_spoof':box('__visitor_network',(0,-10.5,-.015),(22,5,.03))
    elif MODE=='ball_course_role_spoof':
        import bmesh
        obj=roles['lane'][0];mesh=bmesh.new();mesh.from_mesh(obj.data)
        selected=[face for face in mesh.faces if abs(face.calc_center_median().y-2.5)<.4]
        bmesh.ops.delete(mesh,geom=selected,context='FACES');mesh.to_mesh(obj.data);mesh.free();obj.data.update()
        box('__measured_ball_course',(-7,2.5,-.015),(4,1,.03))
    elif MODE=='visitor_thin_neck':
        obj=roles['visitor_path'][-1];obj.location.y=-11.2;obj.scale.y=.25
    elif MODE=='windmill_wrong_lane':
        for obj in roles['windmill']:obj.location.x+=7;obj.location.y-=2
    elif MODE=='castle_wrong_lane':
        for obj in roles['castle_arch']:obj.location.x+=7;obj.location.y-=2
    elif MODE=='windmill_floating':
        for obj in roles['windmill']:obj.location.z+=.25
    elif MODE=='misleading_endpoint_tags':
        for role in ('lane_start','visitor_entry'):
            for obj in roles[role]:obj['bench_role']='irrelevant_annotation'
    elif MODE=='merged_visitor_mesh':
        bpy.ops.object.select_all(action='DESELECT')
        for obj in roles['visitor_path']:obj.select_set(True)
        bpy.context.view_layer.objects.active=roles['visitor_path'][0];bpy.ops.object.join()

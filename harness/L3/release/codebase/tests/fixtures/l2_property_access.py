"""Street/property geometric controls, not complete semantic house answers."""
if NUMBER==3:
    for obj in roles['planter']:obj.location.y+=2
    for owner in roles['house']:
        side=1 if owner.location.x>0 else -1
        box('property_entry',(side*5.85,owner.location.y,-.015),(2.4,1.2,.03))
    first=roles['property_entry'][0]
    if MODE=='missing_entry':bpy.data.objects.remove(first,do_unlink=True)
    elif MODE=='entry_gap':
        y=first.location.y;bpy.data.objects.remove(first,do_unlink=True)
        box('property_entry',(-6.7,y,-.015),(.7,1.2,.03))
        box('property_entry',(-5.25,y,-.015),(1.2,1.2,.03))
    elif MODE=='entry_step':first.location.z+=.3
    elif MODE=='entry_thin':first.scale.y=.25
    elif MODE=='entry_house_gap':first.scale.x=.85;first.location.x+=.18
    elif MODE=='entry_blocked':box('entry_barrier',(-5.7,first.location.y,.2),(.1,1.4,.4))
    elif MODE=='entry_role_spoof':first['bench_role']='__property_floor'
    elif MODE=='short_sidewalk':roles['sidewalk_left'][0].scale.y=.4
    elif MODE=='same_side_walks':roles['sidewalk_left'][0].location.x+=8
    elif MODE=='sidewalk_gap':
        original=roles['sidewalk_left'][0];bpy.data.objects.remove(original,do_unlink=True)
        box('sidewalk_left',(-4,-8,-.015),(1.6,14,.03))
        box('sidewalk_left',(-4,8,-.015),(1.6,14,.03))
    elif MODE=='sidewalk_end_step':
        original=roles['sidewalk_left'][0];bpy.data.objects.remove(original,do_unlink=True)
        box('sidewalk_left',(-4,-.2,-.015),(1.6,29.6,.03))
        box('sidewalk_left',(-4,14.8,.285),(1.6,.4,.03))
    elif MODE=='narrow_sidewalk':roles['sidewalk_left'][0].scale.x=.5
    elif MODE=='sidewalk_edge_planter':box('edge_obstacle',(-4.74,-4,.25),(.12,.2,.5))
    elif MODE=='high_street_barrier':box('over_road_barrier',(0,2,1.3),(6,.1,.3))
    elif MODE=='swapped_sidewalk_tags':
        roles['sidewalk_left'][0]['bench_role']='sidewalk_right'
        roles['sidewalk_right'][0]['bench_role']='sidewalk_left'
    elif MODE=='misleading_street_markers':
        for role in ('road_start','road_end','sidewalk_left_start','sidewalk_left_end','sidewalk_right_start','sidewalk_right_end'):
            for obj in roles[role]:obj['bench_role']='irrelevant_annotation'
    elif MODE=='merged_property_paths':
        bpy.ops.object.select_all(action='DESELECT')
        for obj in roles['property_entry']:obj.select_set(True)
        bpy.context.view_layer.objects.active=roles['property_entry'][0];bpy.ops.object.join()

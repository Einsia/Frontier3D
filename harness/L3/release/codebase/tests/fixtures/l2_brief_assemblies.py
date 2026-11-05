"""Geometric assembly controls; do not claim to be complete textual scenes."""
if NUMBER==3:
    for owner in (roles['house'][0],roles['house'][3]):
        box('chimney',(owner.location.x,owner.location.y,4.35),(.4,.4,.9))
    if MODE=='same_house_chimneys':
        roles['chimney'][1].location.x=roles['house'][0].location.x+.7
        roles['chimney'][1].location.y=roles['house'][0].location.y
    elif MODE=='floating_chimney':roles['chimney'][0].location.z+=1
    elif MODE=='missing_chimney':bpy.data.objects.remove(roles['chimney'][0],do_unlink=True)
    elif MODE=='copied_house_chimney':
        bpy.data.objects.remove(roles['chimney'][0],do_unlink=True)
        owner=roles['house'][0];box('chimney',tuple(owner.location),(4,4,4))
    elif MODE=='flat_chimney':roles['chimney'][0].scale.z=0
    elif MODE=='split_chimney':
        for obj in list(roles['chimney']):
            root=parent('chimney');x,y,z=obj.location
            bpy.data.objects.remove(obj,do_unlink=True)
            box('chimney',(x,y,z-.225),(.4,.4,.45),root)
            box('chimney',(x,y,z+.225),(.4,.4,.45),root)
elif NUMBER==5:
    bed,marker=roles['grave'][:2]
    if MODE=='missing_marker':bpy.data.objects.remove(marker,do_unlink=True)
    elif MODE=='missing_bed':bpy.data.objects.remove(bed,do_unlink=True)
    elif MODE=='lying_marker':marker.rotation_euler.x=math.pi/2;marker.location.z=.3
    elif MODE=='floating_marker':marker.location.z+=.5
    elif MODE=='duplicate_bed_marker':
        owner=marker.parent;bpy.data.objects.remove(marker,do_unlink=True)
        box('grave',tuple(bed.location),tuple(bed.dimensions),owner)
    elif MODE=='far_marker':marker.location.x+=5
    elif MODE=='marker_sheet':marker.scale.y=0
    elif MODE=='joined_parts':
        roots=list(dict.fromkeys(obj.parent for obj in roles['grave']))
        for owner in roots:
            bpy.ops.object.select_all(action='DESELECT')
            pieces=[obj for obj in owner.children if obj.type=='MESH']
            for obj in pieces:obj.select_set(True)
            bpy.context.view_layer.objects.active=pieces[0];bpy.ops.object.join()
            bpy.context.object['bench_part']='deliberately_uninformative'

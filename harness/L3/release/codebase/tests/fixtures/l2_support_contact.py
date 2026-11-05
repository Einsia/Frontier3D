"""Rail-contact augmentation for evaluator-owned numeric controls only."""
if NUMBER == 2:
    for obj in roles['rail_support']:
        obj.dimensions.z = 2.65; obj.location.z = 2.65/2
    vehicle = roles['rail_vehicle'][0]; vehicle.location.z = 3.25
    if MODE == 'support_top_gap':
        obj = roles['rail_support'][0]; obj.dimensions.z = 2.50; obj.location.z = 1.25
    elif MODE == 'support_ground_gap':
        obj = roles['rail_support'][0]; obj.dimensions.z = 2.50; obj.location.z = 1.40
    elif MODE == 'support_lateral_offset':
        roles['rail_support'][0].location.x += 2
    elif MODE in {'support_mid_gap', 'split_rail_support'}:
        obj = roles['rail_support'][0]; position = obj.location.copy()
        bpy.data.objects.remove(obj, do_unlink=True)
        root = parent('rail_support')
        end = 1.20 if MODE == 'support_mid_gap' else 1.30
        box('rail_support', (position.x, position.y, end/2), (.25, .25, end), root)
        box('rail_support', (position.x, position.y, (1.30+2.65)/2), (.25, .25, 2.65-1.30), root)
    elif MODE == 'duplicate_support':
        roles['rail_support'][0].location = roles['rail_support'][1].location.copy()
    elif MODE == 'vehicle_on_ground':
        vehicle.location.z = .5
    elif MODE == 'vehicle_air_gap':
        vehicle.location.z += .1
    elif MODE == 'flat_support':
        roles['rail_support'][0].scale.x = 0
    elif MODE == 'hanging_rail_vehicle':
        # Vehicle sits between columns; its top is attached to rail underside.
        vehicle.location.y = 0; vehicle.location.z = 2.15
    elif MODE == 'disconnected_rail':
        original = roles['rail'][0]; bpy.data.objects.remove(original, do_unlink=True)
        root = parent('rail')
        box('rail', (-10, -5.05, 2.7), (.8, 9.9, .1), root)
        box('rail', (-10, 5.05, 2.7), (.8, 9.9, .1), root)
    elif MODE in {'wheel_assembly', 'joined_rail_vehicle', 'floating_vehicle_body'}:
        bpy.data.objects.remove(vehicle, do_unlink=True)
        root = parent('rail_vehicle')
        body = box('rail_vehicle', (-10, -2, 3.45), (.65, 1.2, .6), root)
        wheels = [box('rail_vehicle', (-10+x, -2+y, 2.95), (.15, .25, .4), root)
                  for x in (-.2, .2) for y in (-.4, .4)]
        if MODE == 'floating_vehicle_body':
            body.location.z += .15
        if MODE == 'joined_rail_vehicle':
            bpy.ops.object.select_all(action='DESELECT')
            for obj in [body, *wheels]:obj.select_set(True)
            bpy.context.view_layer.objects.active = body
            bpy.ops.object.join()

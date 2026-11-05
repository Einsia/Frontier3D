"""Independent relation mutations applied after the relief fixture construction."""
if MODE == 'wrong_side' and NUMBER == 3:
    roles['house'][0].location.x = 13
elif MODE == 'wrong_side' and NUMBER == 5:
    roles['grave'][0].parent.location.x += 13
elif MODE == 'wrong_rows' and NUMBER == 5:
    roles['grave'][0].parent.location.y += 2
elif NUMBER == 6:
    if MODE == 'wrong_course':
        roles['ball'][0].location.x += 7
        roles['ball'][0].location.y += .3
    elif MODE == 'wrong_start':
        roles['ball'][0].location.y = 0
    elif MODE == 'wrong_ball_size':
        roles['ball'][0].scale *= 1.4
        roles['ball'][0].location.z = .07
    elif MODE == 'blocked_lane':
        box('lane_barrier', (-7, 2, .1), (4, .04, .2))
    elif MODE == 'cup_step':
        roles['cup'][0].location.z += .06
    elif MODE == 'lane_gap':
        import bmesh
        obj = roles['lane'][0]; mesh = bmesh.new(); mesh.from_mesh(obj.data)
        selected = [face for face in mesh.faces if abs(face.calc_center_median().y) < .6]
        bmesh.ops.delete(mesh, geom=selected, context='FACES'); mesh.to_mesh(obj.data); mesh.free(); obj.data.update()
    elif MODE == 'lane_angle':
        from mathutils import Matrix
        center = Vector((-7, 0, 0))
        transform = Matrix.Translation(center) @ Matrix.Rotation(math.radians(8), 4, 'Z') @ Matrix.Translation(-center)
        selected = [roles[key][0] for key in ('lane', 'cup', 'ball', 'diamond_obstacle')] + roles['windmill']
        for obj in selected:
            obj.matrix_world = transform @ obj.matrix_world

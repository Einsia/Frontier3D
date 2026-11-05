"""Blender-native properties; authored labels are not physical evidence."""


def rigid_body_facts(obj, scene):
    body = obj.rigid_body
    if body is None:
        return None
    world = scene.rigidbody_world
    return {key: getattr(body, key) for key in (
        'type', 'mass', 'kinematic', 'enabled', 'collision_shape', 'mesh_source',
        'friction', 'restitution', 'use_margin', 'collision_margin', 'linear_damping',
        'angular_damping', 'use_deactivation', 'use_start_deactivated')} | {
        'collision_collections': list(body.collision_collections),
        'in_world': bool(world and world.collection and obj.name in world.collection.all_objects),
        'scale': list(obj.scale)}


def rigid_world_facts(scene):
    world = scene.rigidbody_world
    if world is None:
        return None
    return {'enabled': world.enabled, 'substeps_per_frame': world.substeps_per_frame,
            'solver_iterations': world.solver_iterations, 'time_scale': world.time_scale,
            'gravity_m_s2': list(scene.gravity), 'use_gravity': scene.use_gravity,
            'cache_start': world.point_cache.frame_start, 'cache_end': world.point_cache.frame_end,
            'cache_baked': world.point_cache.is_baked,
            'constraints': [{'object': o.name, 'type': o.rigid_body_constraint.type,
                            'enabled': o.rigid_body_constraint.enabled,
                            'object1': o.rigid_body_constraint.object1.name if o.rigid_body_constraint.object1 else None,
                            'object2': o.rigid_body_constraint.object2.name if o.rigid_body_constraint.object2 else None}
                           for o in scene.objects if o.rigid_body_constraint]}

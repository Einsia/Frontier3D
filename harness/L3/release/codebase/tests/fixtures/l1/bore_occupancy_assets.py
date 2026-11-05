"""Connected revolved solids with genuine holes, caps, and an axial solid post."""

import math


def geometry(mode, segments=64):
    profiles = {
        'through': [(.012, 0), (.03, 0), (.03, .006), (.012, .006)],
        # The post extends beyond the queried plate thickness at BOTH ends.
        # It is connected below that interval, not a disconnected mesh island.
        'post': [(0, -.002), (.03, -.002), (.03, .006), (.012, .006),
                 (.012, -.001), (.0118, -.001), (.0118, .008), (0, .008)],
        'cap': [(.012, 0), (.03, 0), (.03, .006), (.012, .006),
                (.012, .0032), (0, .0032), (0, .003), (.012, .003)],
        'endcap': [(0, 0), (.03, 0), (.03, .006), (.012, .006), (.012, .00002), (0, .00002)],
        'solid': [(0, -.002), (.03, -.002), (.03, .008), (0, .008)],
    }
    profile = profiles[mode if mode in profiles else 'through']
    vertices, rings, triangles = [], [], []
    for r, z in profile:
        if r == 0:
            rings.append([len(vertices)] * segments)
            vertices.append((0., 0., z))
        else:
            rings.append(list(range(len(vertices), len(vertices) + segments)))
            vertices.extend((r * math.cos(2 * math.pi * i / segments),
                             r * math.sin(2 * math.pi * i / segments), z) for i in range(segments))
    for i, ring in enumerate(rings):
        other = rings[(i + 1) % len(rings)]
        for a in range(segments):
            b = (a + 1) % segments
            face = list(dict.fromkeys((ring[a], ring[b], other[b], other[a])))
            triangles.extend((face[0], face[k], face[k + 1]) for k in range(1, len(face) - 1))
    if mode == 'open':
        triangles = triangles[2 * segments:]
    elif mode == 'inverted':
        triangles = [face[::-1] for face in triangles]
    return vertices, triangles


def build(mode):
    import bpy
    from mathutils import Euler, Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    mesh = bpy.data.meshes.new('MeasuredMesh')
    vertices, triangles = geometry('through' if mode == 'transformed' else mode)
    mesh.from_pydata(vertices, [], triangles)
    mesh.update()
    obj = bpy.data.objects.new('Measured', mesh)
    bpy.context.collection.objects.link(obj)
    if mode == 'transformed':
        transform = Euler((.2, -.3, .4)).to_matrix()
        for vertex in mesh.vertices:
            vertex.co = transform @ vertex.co + Vector((.2, -.1, .3))
        mesh.update()
    bpy.ops.wm.save_as_mainfile(filepath='scene.blend')
    bpy.ops.export_scene.gltf(filepath='scene.glb', export_format='GLB')

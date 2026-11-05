"""Injected into the public numerical fixture before negative mutations.

Height functions are independently constructed numerical control shapes. They
are not model generations or complete scenes satisfying textual semantics.
"""


def remove_role(role):
    for obj in roles.get(role, []):
        bpy.data.objects.remove(obj, do_unlink=True)
    roles[role] = []


def grid_mesh(role, xs, ys, height, holes=()):
    verts = [(x, y, height(x, y)) for y in ys for x in xs]
    faces = []; nx = len(xs)
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
            if any(abs(cx - x) < r - 1e-8 and abs(cy - y) < r - 1e-8 for x, y, r in holes):
                continue
            a = j * nx + i; faces.append((a, a + 1, a + nx + 1, a + nx))
    mesh = bpy.data.meshes.new('numeric_relief'); mesh.from_pydata(verts, [], faces); mesh.update()
    obj = bpy.data.objects.new('numeric_relief', mesh); scene.collection.objects.link(obj)
    return register(obj, role)


def samples(low, high, count, extra=()):
    return sorted(set([low + (high - low) * i / (count - 1) for i in range(count)] + list(extra)))


def terrain_background(x, y):
    if NUMBER != 9 or MODE == 'flat_terrain':
        return 0.
    if MODE == 'tilted_terrain':
        return .01 * x
    return .15 * math.sin(x * .12) * math.sin(y * .09)


def actual_depression(role, cx, cy, radius, depth, rim_height, background):
    def height(x, y):
        r = math.hypot(x - cx, y - cy) / radius
        base = background(x, y)
        if MODE == 'flat_recess':
            return base
        if r < .65:
            if MODE == 'raised_ring_only':
                return base
            sign = 1 if MODE == 'mound' else -1
            return base + sign * depth * (1 - (r / .65) ** 2)
        if r < 1:
            return base + rim_height * math.sin(math.pi * (r - .65) / .35)
        return base
    grid_mesh(role, samples(cx - radius, cx + radius, 25), samples(cy - radius, cy + radius, 25), height)
    if MODE == 'covered_recess':
        z = background(cx, cy) + rim_height + .04
        box('lid', (cx, cy, z), (radius * 2, radius * 2, .02))


if NUMBER in (2, 9):
    remove_role('site'); remove_role('crater')
    if NUMBER == 2:
        patches = [(6, 4, 1.25), (6, 10, 1.25), (12, -4, 1.25), (12, -10, 1.25)]
        sx, sy, grid = 36, 32, 9
    else:
        patches = [(-10, 3, 1.5), (-4, 3, 1.5), (-10, 9, 1.5)]
        sx, sy, grid = 80, 80, 49
    xs = samples(-sx / 2, sx / 2, grid, [c + sign * r for c, y, r in patches for sign in (-1, 1)])
    ys = samples(-sy / 2, sy / 2, grid, [c + sign * r for x, c, r in patches for sign in (-1, 1)])
    grid_mesh('site', xs, ys, terrain_background, patches)
    if MODE == 'covered_terrain':
        grid_mesh('terrain_cover', xs, ys, lambda x, y: 1.5, patches)
    for x, y, r in patches:
        actual_depression('crater', x, y, r, .3, .05, terrain_background)
elif NUMBER == 6:
    remove_role('lane'); remove_role('cup')
    # The broad construction base stays below the bottom of the real cups.
    roles['site'][0].location.z = -.5
    for x in (-7, 0, 7):
        r = .2; y = 8
        xs = samples(x - 2, x + 2, 9, [x - r, x + r])
        ys = samples(-10, 10, 21, [y - r, y + r])
        grid_mesh('lane', xs, ys, lambda x, y: 0., [(x, y, r)])
        actual_depression('cup', x, y, r, .16, .012, lambda x, y: 0.)

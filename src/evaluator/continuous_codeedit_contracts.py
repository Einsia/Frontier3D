"""Public-datum mechanical probes for all fifteen frozen L1 editing tasks.

Coordinates below are millimetres from instruction.md and the public initial
CAD/Blender source. Expected values remain public requirements. Private targets
are used subsequently for collector controls, never to fit candidate poses.
"""
import copy
import math

from .continuous_numeric import basis

X, Y, Z = [1, 0, 0], [0, 1, 0], [0, 0, 1]


def metres(values): return [float(x)/1000 for x in values]


def circle(center, axis, diameter, **extra):
    return {'kind': 'circle', 'center_m': metres(center), 'axis': axis,
            'radius_hint_m': diameter/2000, 'search_radius_m': diameter/1000, **extra}


def line(origin, axis, *, mode='bracket', window=(-100, 100), **extra):
    return {'kind': 'line', 'origin_m': metres(origin), 'axis': axis,
            'mode': mode, 'window_m': metres(window), **extra}


def angular_arc(axis, predicate):
    frame = basis(axis)
    angles = [2*math.pi*(i+.5)/128 for i in range(128)]
    selected = [a for a in angles if predicate(frame[:, 0]*math.cos(a)+frame[:, 1]*math.sin(a))]
    if len(selected) < 8: raise ValueError('Public arc too small for a stable fit')
    return selected


def make_contract(plan):
    number = int(plan['task_id'].rsplit('_', 1)[1])
    atoms = {a['id'].removeprefix('numeric_'): a for a in plan['measurements'] if a['method'] == 'normalized_error_kernel'}
    groups = {}

    def add(name, probe, *, value=None, expected=None, **transform):
        parameter = atoms[name]['parameters']
        if expected is None: expected = parameter['public_nominal']
        if isinstance(expected, list): raise ValueError('Vector requirements need explicit instance probes')
        result = {**copy.deepcopy(probe), 'value': value or ('diameter_m' if probe['kind'] == 'circle' else 'distance_m'),
                  'expected': float(expected)/1000, 'tolerance_m': parameter['tolerance_mm']/1000, **transform}
        groups.setdefault('numeric_'+name, []).append(result)

    if number == 1:
        short = [(55, y, 1.) for y in (-18, -8)]
        bridge = [(55, y, 3.) for y in (-37, -27)]
        for center in short+bridge:
            add('rear_hole.diameter', circle(center, Z, 2.7))
        for centers, edges in ((short, [-21, -5]), (bridge, [-40, -24])):
            for i, (center, edge) in enumerate(zip(centers, edges)):
                sign = 1 if i == 0 else -1
                add('rear_hole.edge_offset', circle(center, Z, 2.7), value='center_world_m',
                    component=1, multiply=sign, value_offset_m=-sign*edge/1000)
            add('rear_hole.pair_spacing', {'kind': 'pair_distance', 'distance_component': 1,
                'probes': [circle(c, Z, 2.7) for c in centers]})
        for _, y, _ in short:
            for angle in (math.pi/6, math.pi/2, 5*math.pi/6):
                add('short_jaw.nut_across_flats', line([55,y,4.], [math.cos(angle),math.sin(angle),0], window=(-4,4)))
            add('short_jaw.nut_depth', line([55,y+2.,5.], [0,0,-1], mode='first_positive', window=(0,6)))
        for _, y, _ in bridge:
            add('bridge.counterbore_diameter', circle([55,y,1.], Z, 4.6))
            add('bridge.counterbore_depth', line([55,y+1.8,0.], Z, mode='first_positive', window=(0,7)))
        for x in (47.,50.,53.):
            add('bridge.slot_width', line([x,-32,4.], Y, window=(-6,6)))
            add('bridge.slot_depth', line([x,-32,6.2], [0,0,-1], mode='first_positive', window=(0,7)))
    elif number == 2:
        for x in (9.16,42.5,75.84):
            for z in (1.,2.,3.):
                p = circle([x,0,z], Z, 4.3)
                add('hole.diameter', p)
                add('base_hole.x_from_left', p, value='center_world_m', component=0, expected=x)
        for x in (2.,83.):
            for z in (9.16,35.2,61.24):
                p = circle([x,0,z], X, 4.3)
                add('hole.diameter', p)
                add('side_hole.z_from_bottom', p, value='center_world_m', component=2, expected=z)
        # Avoid the specified base and upright bores when measuring solid web
        # thickness. A line through a bore measures its chord instead.
        for x in (6.,79.):
            for z in (6.,16.): add('gusset.thickness', line([x,0,z], Y, window=(-12,12)))
    elif number == 3:
        for i in range(6):
            angle = i*math.pi/3
            for z in (-5.,-3.):
                add('hole.diameter', circle([16.7*math.cos(angle),16.7*math.sin(angle),z], Z, 5.3))
        for z in (0.,3.):
            for axis, size in ((X,28.),(Y,18.)):
                add('pocket.size_xy', line([0,0,z], axis), expected=size)
        for x in (-4.,0.,4.):
            add('pocket.depth', line([x,0,6.], [0,0,-1], mode='first_positive', window=(0,13)))
    elif number == 4:
        for x in (-60.,-50.,-40.):
            add('boss.outer_diameter', circle([x,0,0], X, 18., boundary='outer', search_radius_m=.012))
            add('bore.diameter', circle([x,0,0], X, 8.))
        for y in (-6.,6.):
            add('boss.projection_from_left_face', line([-35.415,y,0], [-1,0,0], mode='last_positive', window=(0,50)))
        for x in (-30.,25.,30.): add('bore.diameter', circle([x,0,0], X, 8.))
    elif number == 5:
        for y in (-6.,6.):
            add('outlet.projection_from_right_face', line([25.97,y,0], X, mode='last_positive', window=(0,40)))
        for x in (-20.,0.,20.,30.,45.): add('bore.diameter', circle([x,0,0], X, 10.5))
    elif number == 6:
        for i in range(6):
            angle = i*math.pi/3; x,y = 16.5*math.cos(angle),16.5*math.sin(angle)
            for z in (1.,2.,3.):
                p = circle([x,y,z], Z, 4.3)
                add('mount.diameter', p)
                add('mount.pitch_diameter', p, value='center_world_m', norm_components=[0,1], multiply=2)
            add('chamfer.leg', circle([x,y,.1], Z, 4.8), value='radius_m', value_offset_m=(.1-2.15)/1000)
        for z in (5.,12.,20.): add('center_bore.diameter', circle([0,0,z], Z, 12.5))
        for angle in (math.pi/6,math.pi/2,5*math.pi/6):
            add('flange.thickness', line([19*math.cos(angle),19*math.sin(angle),2.], Z, window=(-5,8)))
        for z,outer in ((.1,21.25),(27.3,10.76)):
            add('chamfer.leg', circle([0,0,z], Z, 2*outer, boundary='outer', search_radius_m=(outer+1)/1000),
                value='radius_m', multiply=-1, value_offset_m=(outer+.1)/1000)
            add('chamfer.leg', circle([0,0,z], Z, 13.), value='radius_m', value_offset_m=(.1-6.25)/1000)
    elif number == 7:
        for z in (-5.,5.,15.):
            for axis, value in ((X,19.56),(Y,10.55)):
                for sign in (-1,1):
                    origin = [0.,0.,z]; origin[axis.index(1)] = sign*value
                    add('wall.thickness', line(origin, axis, window=(-6,6)))
        for x in (-5.,0.,5.): add('floor.thickness', line([x,0,-18.35], Z, window=(-5,5)))
        for x in (-14.567,14.567):
            for y in (-8.26,8.26):
                arc = angular_arc(Z, lambda d: d[1]*y < -1 and d[0]*x < -1)
                for z in (-16.,-14.,-12.):
                    add('boss.outer_diameter', circle([x,y,z], Z, 7., boundary='outer', search_radius_m=.0045, angles=arc))
                    add('boss.bore_diameter', circle([x,y,z], Z, 3.2))
                add('boss.bore_diameter', circle([x,y,-18.], Z, 3.2))
                add('boss.height_from_new_floor', line([x,y-math.copysign(2.5,y),-17.1], Z,
                    mode='first_positive', window=(0,12)))
    elif number == 8:
        for x in (-32.,-64/3,-32/3,0.,32/3,64/3,32.):
            for z in (7.,10.,13.):
                p = line([x,0,z], X, window=(-5,5))
                add('fin.thickness', p)
                if abs(x) == 32:
                    add('fin.center_x_endpoints', p, value='center_world_m', component=0, expected=x)
                add('fin.length', line([x,0,z], Y, window=(-30,30)))
            for y in (-8.,0.,8.):
                add('fin.height_above_base', line([x,y,4.], Z, mode='first_positive', window=(0,20)))
    elif number == 9:
        for z in (30.,50.,100.,150.,170.): add('bore.diameter', circle([0,0,z], Z, 12.))
        for z in (5.,10.,190.,195.): add('counterbore.diameter', circle([0,0,z], Z, 20.))
        for start,axis in ((0.,Z),(200.,[0,0,-1])):
            for x,y in ((8.,0.),(-8.,0.),(0.,8.),(0.,-8.)):
                add('counterbore.depth', line([x,y,start], axis, mode='first_positive', window=(0,40)))
        for z in (80.,120.):
            for x in (-18.,-12.,12.,18.):
                p = circle([x,0,z], X, 6.)
                add('cross_hole.diameter', p)
                add('cross_hole.centers_z', p, value='center_world_m', component=2, expected=z)
                add('cross_hole.center_y', p, value='center_world_m', component=1)
    elif number == 10:
        for name,z in (('middle.square_width',31.65),('top.square_width',63.299)):
            for axis in (X,Y): add(name, line([0,0,z], axis, mode='outer_bracket', window=(-40,40)))
        for z in (5.,20.,40.,60.): add('bore.diameter', circle([0,0,z], Z, 18.))
    elif number == 11:
        arc = angular_arc(Z, lambda d: d[0] < .3)
        for z in (2.,5.,9.5):
            add('socket.circle_diameter', circle([0,0,z], Z, 5., angles=arc))
            add('socket.flat_x', line([0,0,z], X, mode='first_positive', window=(0,4)))
        for x,y in ((0.,0.),(-1.,0.),(0.,1.)):
            add('socket.depth', line([x,y,0], Z, mode='first_positive', window=(0,20)))
        for x in (3.,4.,5.):
            p = circle([x,0,8.], X, 2.)
            add('radial_hole.diameter', p)
            add('radial_hole.center_z', p, value='center_world_m', component=2)
            add('radial_hole.center_y', p, value='center_world_m', component=1)
    elif number == 12:
        for i in range(8):
            a = i*math.pi/4
            for radius in (15.,23.):
                add('spoke.width', line([radius*math.cos(a),radius*math.sin(a),3.], [-math.sin(a),math.cos(a),0], window=(-6,6)))
        for z in (1.,3.,5.): add('center_bore.diameter', circle([0,0,z], Z, 10.))
        for x,y in ((32.,0.),(-32.,0.),(0.,32.),(0.,-32.)):
            for z in (1.,3.):
                p = circle([x,y,z], Z, 3.2)
                add('mount.diameter', p)
                add('mount.pitch_diameter', p, value='center_world_m', norm_components=[0,1], multiply=2)
            add('counterbore.diameter', circle([x,y,5.25], Z, 5., search_radius_m=.0029))
            direction = [x/32,y/32]
            add('counterbore.depth', line([x+2*direction[0],y+2*direction[1],6.], [0,0,-1], mode='first_positive', window=(0,7)))
    elif number == 13:
        for x in (18.,22.,30.,34.,39.):
            add('branch.outer_diameter', circle([x,0,25.], X, 24., boundary='outer', search_radius_m=.014))
        for x in (18.,22.,30.,34.): add('branch.bore_diameter', circle([x,0,25.], X, 16.))
        for x in (37.,39.,41.): add('socket.diameter', circle([x,0,25.], X, 20.))
        for y,z in ((9.,25.),(-9.,25.),(0.,34.),(0.,16.)):
            add('socket.depth', line([42.,y,z], [-1,0,0], mode='first_positive', window=(0,15)))
        for y in (-10.,10.):
            p = circle([26.,y,25.], Y, 4.)
            add('radial_hole.diameter', p)
            add('radial_hole.center_x', p, value='center_world_m', component=0)
        for y in (-11.,11.): add('branch.end_x', line([12.,y,25.], X, mode='last_positive', window=(0,45)), value_offset_m=.012)
    elif number == 14:
        for y in (-13.,13.):
            for z in (1.,4.,7.):
                p = line([0,y,z], Y, window=(-8,8))
                add('slot.width', p)
                add('slot.centers_y', p, value='center_world_m', component=1, expected=y)
                add('slot.total_length', line([0,y,z], X, window=(-25,25)))
                for x in (-16.,16.):
                    arc = angular_arc(Z, lambda d: d[0]*x > 4)
                    p = circle([x,y,z], Z, 6., angles=arc, search_radius_m=.005)
                    add('slot.end_radius', p, value='radius_m')
                    add('slot.end_centers_x', p, value='center_world_m', component=0, expected=x)
        for x in (-30.,30.):
            for z in (1.,3.,4.):
                p = circle([x,0,z], Z, 5.)
                add('hole.diameter', p)
                add('hole.centers_x', p, value='center_world_m', component=0, expected=x)
                add('hole.center_y', p, value='center_world_m', component=1)
            for z in (6.,7.): add('counterbore.diameter', circle([x,0,z], Z, 9.))
            for y in (-3.5,3.5): add('counterbore.depth', line([x,y,8.], [0,0,-1], mode='first_positive', window=(0,9)))
    elif number == 15:
        for z in (1.,3.,5.): add('center_bore.radius', circle([0,0,z], Z, 24.), value='radius_m')
    else: raise ValueError('No public CodeEdit measurement contract')
    if set(groups) != {'numeric_'+name for name in atoms}: raise ValueError('Incomplete CodeEdit numeric contract')
    preserve = next(a['parameters']['half_scale_m'] for a in plan['measurements'] if a['id'] == 'protected_native')
    return {'version': 'continuous-codeedit-native-v2', 'task_id': plan['task_id'],
        'status': 'requires_reference_and_negative_controls', 'registration': 'none',
        'expected_authority': 'instruction.md; public initial CAD source for datums and inherited axes',
        'source_bindings': plan['source_bindings'], 'numeric_probes': groups,
        'format_aggregation': 'minimum_native_glb', 'scope_epsilon_m': min(1e-7, preserve/10),
        'protected_properties': {'groups': ['material_parameters','piece_count','independent_editability'],
            'material_half_scale': 1e-5, 'material_tolerance': 1e-6,
            'part_assignment': 'minimum_fixed_world_bbox_centre_distance; no scene transform',
            'camera_preservation_applicable': False,
            'camera_scope_authority': 'instruction.md requires original part pose and materials; no retained camera requirement'}}

"""Independent analytic CSG oracle and measured scene constraint checks."""
import math

def inside_primitive(point,op):
    x,y,z=[point[i]-op['at'][i] for i in range(3)]
    a=math.radians(-op.get('rotation_z',0));x,y=x*math.cos(a)-y*math.sin(a),x*math.sin(a)+y*math.cos(a)
    if op.get('axis')=='x':x,z=-z,x
    if op.get('axis')=='y':y,z=z,-y
    if op['shape']=='box':return all(abs(v)<=s/2 for v,s in zip([x,y,z],op['size']))
    height=op['height']
    if abs(z)>height/2:return False
    r=op['radius']+(op.get('radius_top',op['radius'])-op['radius'])*(z/height+.5)
    sides=op.get('vertices',96)
    if sides<20:
        # Exact regular polygon cross section, with a vertex on +X.
        vertices=[(r*math.cos(i*2*math.pi/sides+math.pi/2),r*math.sin(i*2*math.pi/sides+math.pi/2)) for i in range(sides)]
        return all((vertices[(i+1)%sides][0]-p[0])*(y-p[1])-(vertices[(i+1)%sides][1]-p[1])*(x-p[0])>=-1e-9 for i,p in enumerate(vertices))
    return x*x+y*y<=r*r

def analytic_inside(point_m,spec):
    point=[v*1000 for v in point_m];inside=False
    for op in spec['operations']:
        value=inside_primitive(point,op)
        inside=(inside or value) if op.get('op','union')=='union' else inside and not value
    return inside

def scene_checks(spec,geometry,initial=None,position_tolerance=.012):
    checks=[]
    def add(name,value,detail=None):checks.append(dict(name=name,passed=bool(value),detail=detail))
    objects=spec['objects'];expected={o['id'] for o in objects}
    add('unique_named_objects',len(expected)==len(objects) and set(geometry)==expected)
    for o in objects:
        g=geometry.get(o['id'])
        if not g:continue
        low,high=g['bounds'];center=[(low[i]+high[i])/2 for i in [0,1]]+[low[2]]
        add('placement:'+o['id'],max(abs(center[i]-o['at'][i]) for i in range(3))<position_tolerance)
        a=math.radians(o.get('yaw',0));sx,sy,sz=o['size']
        # Rotated AABB dimensions: exact for boxes, upper bound for asymmetrical meshes.
        dims=[abs(math.cos(a))*sx+abs(math.sin(a))*sy,abs(math.sin(a))*sx+abs(math.cos(a))*sy,sz]
        if o.get('yaw',0)%90==0:
            add('scale:'+o['id'],max(abs(g['dimensions'][i]-dims[i]) for i in range(3))<.012)
        add('parent:'+o['id'],g['parent']=='zone_'+o.get('zone','main'))
        if not o.get('asset'):
            colors=g.get('material_colors',[])
            add('material_color:'+o['id'],bool(colors) and max(abs(x-y) for x,y in zip(colors[0],o.get('color',[.55,.58,.6])))<.001)
    if spec['level']==2:
        aisle=spec['aisle']
        blockers=[]
        for name,g in geometry.items():
            if name=='floor' or name.startswith('wall_'):continue
            lo,hi=g['bounds']
            if lo[2]<2 and hi[2]>0 and hi[0]>aisle['x_min'] and lo[0]<aisle['x_max'] and hi[1]>aisle['y_min'] and lo[1]<aisle['y_max']:blockers.append(name)
        add('continuous_1.8m_aisle',not blockers,blockers)
        # Each floor-bound object uses its measured bottom rather than its declared position.
        for o in objects:
            if o.get('asset') and o['at'][2]==0:add('ground_contact:'+o['id'],abs(geometry[o['id']]['bounds'][0][2])<.002)
        for o in objects:
            if o['id'].endswith('_prop'):
                support=o['id'][:-5];prop=geometry[o['id']];table=geometry[support]
                add('support_contact:'+o['id'],abs(prop['bounds'][0][2]-table['bounds'][1][2])<.002)
        if initial:
            for name,g in initial.items():
                if name not in spec.get('edit_ids',[]):
                    add('preserved:'+name,name in geometry and geometry[name]['geometry_sha256']==g['geometry_sha256'] and geometry[name]['parent']==g['parent'] and geometry[name]['material_signature']==g['material_signature'])
    return checks

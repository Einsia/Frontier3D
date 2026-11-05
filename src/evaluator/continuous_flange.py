"""Public feature/placement measurements for Text2Code 001's eleven parts.

Role assignment uses observed dimensions and heights. Every assigned part is
then checked using actual sections, holes and independent editability. Names
never supply a role or a measurement. XY origin and bolt-pattern phase are free.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment
from .continuous_assembly_features import Part,quantity,circular_rows,bore_rows,hexagon_rows,selected_loop
from .continuous_numeric import line_intersections
from .continuous_sweep import grouped
from .continuous_v2_tasks import measure

CONTRACT={'task_id':'L1/Text2Code/task_L1_Text2Code_001','tolerance_m':.0003,
    'roles':{'flange':2,'shaft':1,'bolt':4,'washer':4},
    'flange':{'diameter_m':.09,'height_m':.012,'bore_m':.0204,'holes':4,'hole_m':.0064,'pitch_m':.064},
    'shaft':{'diameter_m':.02,'length_m':.046},
    'bolt':{'shank_m':.006,'shank_length_m':.0275,'head_height_m':.004,'head_circumdiameter_m':.0108},
    'washer':{'outer_m':.012,'inner_m':.0064,'height_m':.0015},
    'sections':[.125,.375,.625,.875],'height_rays':32,
    'role_assignment':'one-to-one public dimension/height cost, followed by actual feature measurements',
    'datum':'observed lower-flange XY axis; world Z unchanged; no prescribed pattern phase',
    'registration':'none','physics_scoring':False}


def assign(parts):
    slots=[('flange',0),('flange',1),('shaft',0),*[('bolt',i) for i in range(4)],*[('washer',i) for i in range(4)]]
    expected={'flange':[.09,.09,.012],'shaft':[.02,.02,.046],'bolt':[.0108,.0108,.0315],'washer':[.012,.012,.0015]}
    if not parts:return {slot:None for slot in slots},[]
    cost=[]
    for role,index in slots:
        extent=np.asarray(expected[role]);z=.014*index if role=='flange' else -.003 if role=='shaft' else .026 if role=='washer' else 0.
        cost.append([float(np.mean(np.abs(np.log(np.maximum(p.high-p.low,1e-12)/extent))))+
                     abs(p.low[2]-z)/max(extent[2],.012) for p in parts])
    rows,columns=linear_sum_assignment(cost);mapping={slot:None for slot in slots}
    for row,column in zip(rows,columns):mapping[slots[int(row)]]=int(column)
    return mapping,cost


def missing(reason):return {'status':'absent','reason':reason}


def features(parts,evidence):
    if not evidence:raise ValueError('Bound assembly geometry required')
    mapping,cost=assign(parts)
    groups={name:{} for name in ('part_roles','flange_dimensions','flange_bores','shaft_dimensions',
                                 'bolt_features','washer_features','assembly')}
    if not parts:
        return {'measurements':{'numeric_'+key:{'status':'absent','reason':'Required assembly has no geometric part',
                    'evidence':evidence} for key in [*groups,'clearance']},
                'assignment':{role+'-'+str(i):None for role,i in mapping},'assignment_cost':cost,
                'part_observations':{},'contract':CONTRACT}
    details={};holes={};role_proofs={}
    def add(group,key,rows):groups[group][key]=rows if isinstance(rows,list) else [rows]
    def get(slot):return None if mapping[slot] is None else parts[mapping[slot]]
    for slot,index in mapping.items():
        role,i=slot;key=role+'-'+str(i);part=get(slot)
        if part is None:
            role_proofs[key]=[missing('Required independent '+role+' absent')]
            population={
                'flange':{'flange_dimensions':[key+'-diameter',key+'-thickness'],
                    'flange_bores':[key+'-center-bore',key+'-hole-count',
                        *(key+'-hole-'+str(h) for h in range(4)),key+'-angular-spacing']},
                'shaft':{'shaft_dimensions':['diameter','length']},
                'bolt':{'bolt_features':[key+'-shank-diameter',key+'-hex-head',key+'-shank-length',key+'-head-height']},
                'washer':{'washer_features':[key+'-diameter',key+'-bore',key+'-thickness']}}[role]
            for name,identities in population.items():
                for identity in identities:add(name,identity,missing('Required '+role+' absent'))
            add('assembly',key+('-bottom' if role=='bolt' else '-height'),missing('Required '+role+' placement absent'));continue
        metadata={'object_index':index,'object':part.metadata.get('object'),'bounds_m':[part.low.tolist(),part.high.tolist()]}
        details[key]=metadata
        axis=part.center.copy();middle=part.at(float(part.center[2]));outer=selected_loop(middle)
        if outer is not None:axis[:2]=outer['center_world_m'][:2]
        details[key]['axis_world_m']=axis.tolist()
        shape=[]
        if outer is not None:
            shape.append(quantity(outer['max_circular_deviation_m'],0.,{'section':middle}))
        else:shape.append(missing('No closed outside section'))
        if role=='flange':
            add('flange_dimensions',key+'-diameter',circular_rows(part,.09))
            add('flange_dimensions',key+'-thickness',quantity(float(part.high[2]-part.low[2]),.012,metadata))
            central=bore_rows(part,axis,.0204)
            add('flange_bores',key+'-center-bore',central)
            cavities=[] if middle['status']!='measured' else [r for r in middle['loops'] if r['kind']=='cavity']
            cavities.sort(key=lambda r:np.linalg.norm(np.asarray(r['center_world_m'])[:2]-axis[:2]))
            bolt_holes=cavities[1:]
            bolt_holes.sort(key=lambda r:np.arctan2(r['center_world_m'][1]-axis[1],r['center_world_m'][0]-axis[0]))
            holes[i]=bolt_holes[:4]
            add('flange_bores',key+'-hole-count',quantity(len(bolt_holes),4,{'section':middle},tolerance=0.,half_scale=1.))
            for h in range(4):
                if h>=len(bolt_holes):
                    add('flange_bores',key+'-hole-'+str(h),missing('Required pitch-circle bore absent'));continue
                c=np.asarray(bolt_holes[h]['center_world_m'])
                rows=bore_rows(part,c,.0064)
                rows.append(quantity(float(2*np.linalg.norm(c[:2]-axis[:2])),.064,{'center_world_m':c.tolist(),'axis_world_m':axis.tolist()}))
                add('flange_bores',key+'-hole-'+str(h),rows)
            if len(bolt_holes)==4:
                vectors=np.array([r['center_world_m'][:2] for r in bolt_holes])-axis[:2]
                angles=np.mod(np.roll(np.arctan2(vectors[:,1],vectors[:,0]),-1)-np.arctan2(vectors[:,1],vectors[:,0]),2*np.pi)
                add('flange_bores',key+'-angular-spacing',quantity((angles*.032).tolist(),[np.pi/2*.032]*4,{'angles_radians':angles.tolist()}))
            else:add('flange_bores',key+'-angular-spacing',missing('Four measured bolt-hole centres required'))
            shape.append(quantity(len(cavities),5,{'section':middle},tolerance=0.,half_scale=1.))
            add('assembly',key+'-height',quantity(float(part.low[2]),i*.014,metadata))
        elif role=='shaft':
            add('shaft_dimensions','diameter',circular_rows(part,.02))
            add('shaft_dimensions','length',quantity(float(part.high[2]-part.low[2]),.046,metadata))
            add('assembly',key+'-height',quantity(float(part.center[2]),.020,metadata))
        elif role=='washer':
            add('washer_features',key+'-diameter',circular_rows(part,.012))
            add('washer_features',key+'-bore',bore_rows(part,axis,.0064))
            add('washer_features',key+'-thickness',quantity(float(part.high[2]-part.low[2]),.0015,metadata))
            shape.extend(bore_rows(part,axis,.0064))
            add('assembly',key+'-height',quantity(float(part.low[2]),.026,metadata))
        else:
            head_bottom=float(part.high[2]-.004)
            add('bolt_features',key+'-shank-diameter',circular_rows(part,.006,span=(float(part.low[2]),head_bottom)))
            head=hexagon_rows(part,(head_bottom,float(part.high[2])),.0108)
            add('bolt_features',key+'-hex-head',head);shape=head
            length_rows=[];height_rows=[]
            for angle in np.arange(32)*2*np.pi/32:
                origin=np.array([axis[0]+.004*np.cos(angle),axis[1]+.004*np.sin(angle),0.])
                hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,[0.,0.,1.])
                observation={'origin_world_m':origin.tolist(),'intersections_m':hits.tolist()}
                length_rows.append(quantity(None if len(hits)<2 else float(hits[0]-part.low[2]),.0275,observation))
                height_rows.append(quantity(None if len(hits)<2 else float(hits[-1]-hits[0]),.004,observation))
            add('bolt_features',key+'-shank-length',length_rows);add('bolt_features',key+'-head-height',height_rows)
            add('assembly',key+'-bottom',quantity(float(part.low[2]),0.,metadata))
        editable=bool(part.metadata.get('editable',True)) and not part.metadata.get('instance',False)
        shape.append(quantity(1 if editable else None,1,
                              {'object':part.metadata.get('object'),'independent_editability':editable},
                              tolerance=0.,half_scale=1.))
        role_proofs[key]=shape
    # Keep all eleven expected parts in the semantic denominator. Any excess
    # or missing objects also retain an explicit, continuous count residual.
    groups['part_roles']=role_proofs
    add('part_roles','total-count',quantity(len(parts),11,{'observed_objects':len(parts)},tolerance=0.,half_scale=1.))
    lower=get(('flange',0));datum=None if lower is None else np.asarray(details['flange-0']['axis_world_m'])
    for slot in [('flange',1),('shaft',0)]:
        key=slot[0]+'-'+str(slot[1]);axis=details.get(key,{}).get('axis_world_m')
        add('assembly',key+'-coaxial',quantity(None if datum is None or axis is None else
            float(np.linalg.norm(np.asarray(axis)[:2]-datum[:2])),0.,{'axis_world_m':axis,'datum_world_m':None if datum is None else datum.tolist()}))
    if lower is not None and get(('flange',1)) is not None:
        add('assembly','flange-gap',quantity(float(get(('flange',1)).low[2]-lower.high[2]),.002,details))
    else:add('assembly','flange-gap',missing('Both flange surfaces required'))
    # Relative correspondence across the two measured four-hole patterns is
    # assignment only: coordinates and orientations remain unchanged.
    upper_holes=holes.get(1,[]);lower_holes=holes.get(0,[])
    for label,points in [('upper-holes',[r['center_world_m'] for r in upper_holes]),
                         ('bolts',[details['bolt-'+str(i)]['axis_world_m'] for i in range(4) if 'bolt-'+str(i) in details]),
                         ('washers',[details['washer-'+str(i)]['axis_world_m'] for i in range(4) if 'washer-'+str(i) in details])]:
        observed=[]
        if lower_holes and points:
            distance=np.linalg.norm(np.asarray([r['center_world_m'][:2] for r in lower_holes])[:,None,:]-np.asarray(points)[None,:,:2],axis=2)
            rows,cols=linear_sum_assignment(distance);observed=[quantity(float(distance[a,b]),0.,
                {'lower_hole_world_m':lower_holes[a]['center_world_m'],'other_world_m':points[b]}) for a,b in zip(rows,cols)]
        observed.extend(missing('Corresponding hole/fastener axis absent') for _ in range(4-len(observed)))
        add('assembly',label+'-alignment',observed)
    result={'numeric_'+key:grouped(value,evidence,public_contract=CONTRACT) for key,value in groups.items()}
    # Pairwise interior overlap needs a separate complete-surface collector.
    # Dimensional clearance evidence is retained without claiming that gate.
    result['numeric_clearance']={'status':'technical_failure','reason':'Pairwise solid-interior overlap collector pending',
        'evidence':evidence,'available_geometric_evidence':['numeric_flange_bores','numeric_shaft_dimensions','numeric_bolt_features','numeric_assembly']}
    return {'measurements':result,'assignment':{role+'-'+str(i):index for (role,i),index in mapping.items()},
            'assignment_cost':cost,'part_observations':details,'contract':CONTRACT}

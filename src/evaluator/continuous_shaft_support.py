"""Public part and bore metrology for the sixteen-part Text2Code 002 support."""
import numpy as np
from scipy.optimize import linear_sum_assignment
from .continuous_assembly_features import Part,quantity,circular_rows,bore_rows,hexagon_rows
from .continuous_numeric import line_intersections
from .continuous_sweep import grouped


def public_parts():
    parts=[]
    def add(role,group,kind,center,extent,**extra):
        parts.append({'role':role,'group':group,'kind':kind,'center_m':(np.asarray(center)/1000).tolist(),
                      'extent_m':(np.asarray(extent)/1000).tolist(),**extra})
    add('base','base','box',[0,0,3],[140,70,6])
    for i,x in enumerate((-42,42)):
        add('block-'+str(i),'blocks','box',[x,0,27],[18,48,42],bore={'diameter_m':.0244,'axis':0,'center_m':[x/1000,0.,.034]})
        add('sleeve-'+str(i),'sleeves','tube',[x,0,34],[18,24,24],axis=0,diameter_m=.024,bore_m=.0164)
    add('shaft','shaft','cylinder',[0,0,34],[130,16,16],axis=0,diameter_m=.016)
    for i,x in enumerate((-56,56)):
        add('collar-'+str(i),'collars','tube',[x,0,34],[5,24,24],axis=0,diameter_m=.024,bore_m=.0164)
    for i,(x,y) in enumerate(((-42,-18),(-42,18),(42,-18),(42,18))):
        add('bolt-'+str(i),'fasteners','bolt',[x,y,26.75],[10.8,10.8,53.5],shank_m=.006,shank_length_m=.0495,head_m=.0108,head_height_m=.004)
        add('washer-'+str(i),'fasteners','tube',[x,y,48.75],[12,12,1.5],axis=2,diameter_m=.012,bore_m=.0064)
    return parts


CONTRACT={'task_id':'L1/Text2Code/task_L1_Text2Code_002','tolerance_m':.0003,'parts':public_parts(),
    'mounting_holes':[{'center_m':[x/1000,y/1000,0.],'diameter_m':.0064,'axis':2,'block_role':'block-'+str(i)}
                      for i,x in enumerate((-42,42)) for y in (-18,18)],
    'assignment':'one-to-one complete surface extent and public world-centre cost; no names or fitted transform',
    'registration':'none','physics_scoring':False}


def assign(parts):
    definitions=CONTRACT['parts'];mapping={d['role']:None for d in definitions}
    if not parts:return mapping,[]
    costs=[]
    for definition in definitions:
        expected=np.asarray(definition['extent_m']);centre=np.asarray(definition['center_m'])
        costs.append([float(np.mean(np.abs(np.log(np.maximum(p.high-p.low,1e-12)/expected))))+
                      float(np.linalg.norm((p.center-centre)/np.maximum(expected,.01))) for p in parts])
    rows,cols=linear_sum_assignment(costs)
    for i,j in zip(rows,cols):mapping[definitions[int(i)]['role']]=int(j)
    return mapping,costs


def features(parts,evidence):
    mapping,cost=assign(parts);groups={g:{} for g in ('part_roles','base','blocks','sleeves','shaft','collars','mounting_passages','fasteners')}
    if not parts:
        return {'measurements':{'numeric_'+g:{'status':'absent','reason':'Required assembly surface absent','evidence':evidence}
                for g in [*groups,'assembly_clearance']},'assignment':mapping,'assignment_cost':cost,'contract':CONTRACT}
    records={};placements=[];openings=[]
    for definition in CONTRACT['parts']:
        role=definition['role'];index=mapping[role];group=groups[definition['group']]
        # A fixed feature list is declared before any candidate is observed.
        expected=['extent','position']
        kind=definition['kind']
        if kind=='box':expected+=['planar_surfaces']
        if kind in ('tube','cylinder'):expected+=['outer_circular_sections','axial_length']
        if kind=='tube' or 'bore' in definition:expected+=['bore']
        if kind=='bolt':expected+=['shank_diameter','shank_length','hex_head','head_height']
        if index is None:
            for key in expected:group[role+'/'+key]=[{'status':'absent','reason':'Required '+role+' absent'}]
            groups['part_roles'][role]=[{'status':'absent','reason':'Required independently editable role absent'}]
            placements.append({'status':'absent','reason':'Required role placement absent','role':role})
            if kind=='tube' or 'bore' in definition:openings.append({'status':'absent','reason':'Required bore role absent','role':role})
            continue
        part=parts[index];raw={'role':role,'object_index':index,'object':part.metadata.get('object'),
            'actual_center_m':part.center.tolist(),'actual_extent_m':(part.high-part.low).tolist(),'public_part':definition}
        records[role]=raw;position=quantity(part.center.tolist(),definition['center_m'],raw)
        extent=quantity(float(part.high[2]-part.low[2]),definition['extent_m'][2],raw) if kind=='bolt' else quantity((part.high-part.low).tolist(),definition['extent_m'],raw)
        group[role+'/extent']=[extent];group[role+'/position']=[position];placements.append({**position,'role':role})
        proof=[]
        if kind=='box':
            xyz=part.mesh.xyz;normal=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);normal/=np.linalg.norm(normal,axis=1)[:,None]
            # Distance of each triangle's vertices to its nearest observed
            # outer box face measures actual structural planes; bore walls
            # are excluded from the expected outside-face population.
            distances=np.minimum(np.abs(xyz-part.low),np.abs(xyz-part.high))
            per_face=distances.max(1).min(1);outer=per_face<=.0003
            represented=[]
            for axis in range(3):
                for sign,plane in ((-1,part.low[axis]),(1,part.high[axis])):
                    area=float(part.mesh.areas[(np.abs(xyz[:,:,axis]-plane).max(1)<=.0003)&(np.abs(normal[:,axis])>.99)].sum())
                    represented.append(quantity(0. if area>0 else None,0.,{'axis':axis,'side':sign,'observed_planar_area_m2':area}))
            group[role+'/planar_surfaces']=represented;proof+=represented
        if kind in ('tube','cylinder'):
            circular=circular_rows(part,definition['diameter_m'],axis=definition['axis'])
            group[role+'/outer_circular_sections']=circular;proof+=circular
            group[role+'/axial_length']=[quantity(float((part.high-part.low)[definition['axis']]),
                definition['extent_m'][definition['axis']],raw)]
        if kind=='tube' or 'bore' in definition:
            bore=definition.get('bore',{'diameter_m':definition.get('bore_m'),'axis':definition.get('axis'),'center_m':definition['center_m']})
            # Feature-local positions follow the measured part datum. The
            # independent world placement residual remains above unchanged.
            center=part.center+np.asarray(bore['center_m'])-np.asarray(definition['center_m'])
            measured=bore_rows(part,center,bore['diameter_m'],axis=bore['axis'])
            group[role+'/bore']=measured;proof+=measured;openings.append({**measured[-1],'role':role})
        if kind=='bolt':
            split=float(part.high[2]-definition['head_height_m'])
            circular=circular_rows(part,definition['shank_m'],span=(float(part.low[2]),split))
            group[role+'/shank_diameter']=circular
            head=hexagon_rows(part,(split,float(part.high[2])),definition['head_m']);group[role+'/hex_head']=head;proof+=head
            shank=[];height=[]
            radius=(definition['shank_m']/2+definition['head_m']*np.sqrt(3)/4)/2
            for angle in np.arange(32)*2*np.pi/32:
                origin=np.array([part.center[0]+radius*np.cos(angle),part.center[1]+radius*np.sin(angle),0.])
                hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,[0,0,1])
                obs={'origin_m':origin.tolist(),'intersections_m':hits.tolist()}
                shank.append(quantity(None if len(hits)<2 else float(hits[0]-part.low[2]),definition['shank_length_m'],obs))
                height.append(quantity(None if len(hits)<2 else float(hits[-1]-hits[0]),definition['head_height_m'],obs))
            group[role+'/shank_length']=shank;group[role+'/head_height']=height
        editable=bool(part.metadata.get('editable',True)) and not part.metadata.get('instance',False)
        proof.append(quantity(0. if editable else None,0.,{'independent_editability':editable}))
        groups['part_roles'][role]=proof
    groups['part_roles']['total_count']=[quantity(len(parts),16,{'observed_parts':len(parts)},tolerance=0.,half_scale=1.)]
    for i,definition in enumerate(CONTRACT['mounting_holes']):
        for role in ('base',definition['block_role']):
            index=mapping[role]
            if index is None:rows=[{'status':'absent','reason':'Required pierced part absent'}]
            else:
                part=parts[index];expected=next(d for d in CONTRACT['parts'] if d['role']==role)
                center=part.center+np.asarray(definition['center_m'])-np.asarray(expected['center_m'])
                rows=bore_rows(part,center,definition['diameter_m'])
            openings.append({**rows[-1],'role':role,'mounting_hole':i})
            groups['mounting_passages'][str(i)+'/'+role]=rows
    measurements={'numeric_'+g:grouped(rows,evidence,public_contract=CONTRACT) for g,rows in groups.items()}
    measurements['numeric_assembly_clearance']={'status':'technical_failure','reason':'Pairwise overlap and relationship composition pending','evidence':evidence}
    return {'measurements':measurements,'assignment':mapping,'assignment_cost':cost,'part_observations':records,
            'placement_observations':placements,'opening_observations':openings,'contract':CONTRACT}

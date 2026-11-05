"""Public coupling dimensions with a freely chosen origin and hole-pattern phase."""
import copy
import numpy as np
from scipy.optimize import linear_sum_assignment
from .continuous_assembly_contracts import part,hole
from .continuous_assembly_layouts import layout,relation
from .continuous_assembly_features import quantity


def coupling():
    parts=[]
    for i,z in enumerate((-11,11)):
        half=part('half-'+str(i),'hub_features','stepped_rotary',[0,0,z],[54,54,18],axis=2,
                  holes=[hole('shaft',2,16.4,[0,0,z])])
        half['outer_profile']=[{'id':'lower_hub','diameter_m':.024,'span_offset_m':[-.009,-.004]},
                               {'id':'flange','diameter_m':.054,'span_offset_m':[-.004,.004]},
                               {'id':'upper_hub','diameter_m':.024,'span_offset_m':[.004,.009]}]
        half['axial_profile_probes']=[{'id':'flange_thickness','radius_m':.0251,'boundary_offsets_m':[-.004,.004]}]
        half['hole_pattern']={'count':3,'pitch_radius_m':.020,'group':'flange_holes'}
        for j in range(3):
            angle=j*2*np.pi/3;x,y=20*np.cos(angle),20*np.sin(angle)
            half['holes'].append(hole('bolt-'+str(j),2,6.4,[x,y,z],group='flange_holes',
                                     section_spans_offset_m=[[-.004,.004]],corridor_span_offset_m=[-.004,.004]))
        parts+=[half,part('shaft-'+str(i),'shafts','cylinder',[0,0,-32 if i==0 else 32],[16,16,24],axis=2,diameter=16)]
    parts.append(part('spacer','spacer','tube',[0,0,0],[28,28,3],axis=2,diameter=28,holes=[hole('axis',2,16.8,[0,0,0])]))
    for i in range(3):
        angle=i*2*np.pi/3;x,y=20*np.cos(angle),20*np.sin(angle)
        screw=part('bolt-'+str(i),'bolts','bolt',[x,y,2.75],[10.8,10.8,35.5])
        screw.update(shank_diameter_m=.006,shank_length_m=.0315,head_diameter_m=.0108,head_height_m=.004)
        parts+=[screw,part('washer-'+str(i),'washers','tube',[x,y,15.75],[12,12,1.5],axis=2,diameter=12,
                          holes=[hole('bolt',2,6.4,[x,y,15.75])])]
    result=layout('015',parts,['hub_features','flange_holes','shafts','spacer','washers','bolts'],
                  [relation('flange_midplanes','hub_features','half-1','half-0',2,bounds=('center','center'),gap=22)],
                  'shaft-0',[0,1],'shafts','hub_features')
    result.update(free_origin_and_pattern_phase=True,require_parent_tree=True,
        datum_policy='complete scene bounds midpoint and observed lower-flange hole phase; no candidate coordinate transform',
        negative_position_role='half-0')
    return result


def with_observed_datum(parts,public):
    contract=copy.deepcopy(public)
    if not parts:return contract
    origin=(np.min([p.low for p in parts],axis=0)+np.max([p.high for p in parts],axis=0))/2
    costs=[]
    for d in public['parts']:
        extent=np.asarray(d['extent_m']);center=origin+np.asarray(d['center_m'])
        costs.append([float(np.abs(np.log(np.maximum(p.high-p.low,1e-12)/extent)).mean())+
                      float(np.linalg.norm((p.center-center)/np.maximum(extent,.01))) for p in parts])
    rows,cols=linear_sum_assignment(costs)
    assignments={public['parts'][int(i)]['role']:int(j) for i,j in zip(rows,cols)}
    phase=0.;observation={'status':'absent','reason':'Lower flange hole pattern absent'}
    if 'half-0' in assignments:
        lower=parts[assignments['half-0']];observation=lower.at(float(lower.center[2]))
        if observation['status']=='measured':
            cavities=[r for r in observation['loops'] if r['kind']=='cavity']
            cavities.sort(key=lambda r:np.linalg.norm(np.asarray(r['center_world_m'])[:2]-lower.center[:2]))
            holes=cavities[1:]
            if holes:
                angles=[float(np.arctan2(r['center_world_m'][1]-lower.center[1],r['center_world_m'][0]-lower.center[0])) for r in holes]
                phase=min(angles)
    rotation=np.array([[np.cos(phase),-np.sin(phase),0],[np.sin(phase),np.cos(phase),0],[0,0,1]])
    for definition in contract['parts']:
        definition['center_m']=(np.asarray(definition['center_m'])@rotation.T+origin).tolist()
        for hole_definition in definition.get('holes',[]):
            hole_definition['center_m']=(np.asarray(hole_definition['center_m'])@rotation.T+origin).tolist()
    contract['observed_datum']={'origin_m':origin.tolist(),'pattern_phase_radians':phase,'lower_pattern_observation':observation,
                                'candidate_transform_applied':False,'public_basis':'origin and Z-axis pattern phase are explicitly free'}
    return contract


def pattern(part,definition):
    specification=definition['hole_pattern'];section=part.at(float(part.center[2]))
    if section['status']=='technical_failure':return {'count':[section],'pitch':[section],'spacing':[section]}
    cavities=[] if section['status']!='measured' else [r for r in section['loops'] if r['kind']=='cavity']
    cavities.sort(key=lambda r:np.linalg.norm(np.asarray(r['center_world_m'])[:2]-part.center[:2]));holes=cavities[1:]
    raw={'section':section};count=specification['count'];radius=specification['pitch_radius_m']
    result={'count':[quantity(len(holes) if cavities else None,count,raw,tolerance=0.,half_scale=1.)]}
    vectors=np.array([r['center_world_m'][:2] for r in holes])-part.center[:2] if holes else np.empty((0,2))
    angles=np.sort(np.arctan2(vectors[:,1],vectors[:,0]))
    if len(holes)==count:
        result['pitch']=[quantity(np.linalg.norm(vectors,axis=1).tolist(),[radius]*count,raw)]
        gaps=np.mod(np.roll(angles,-1)-angles,2*np.pi)
        result['spacing']=[quantity((gaps*radius).tolist(),[2*np.pi/count*radius]*count,raw)]
    else:
        result.update(pitch=[quantity(None,radius,raw)],spacing=[quantity(None,2*np.pi/count*radius,raw)])
    return result

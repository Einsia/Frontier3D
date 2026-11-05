"""Export material equivalence from assigned surface slots in fixed coordinates."""
import numpy as np
from .continuous_edit_properties import assignments,material_parameters,FIELDS
from .continuous_numeric import scalar_error
from .continuous_surface import triangle_areas,area_samples
from .l1_surface import SurfaceMesh,_distances_to_triangles


def parameters(obj,slot):
    materials=obj['materials']
    material=materials[slot] if 0<=slot<len(materials) else None
    return None if material is None else material_parameters(material)


def parameter_score(actual,expected,tolerance,half_scale):
    if actual is None or expected is None:
        return (1. if actual is None and expected is None else 0.),{'assignment_state':'both_unassigned' if actual is expected else 'assignment_changed'}
    values=[];rows=[]
    for key in FIELDS:
        if actual[key] is None or expected[key] is None:
            return None,{'reason':'Assigned procedural property requires surface shader sampling','field':key}
        errors=scalar_error(actual[key],expected[key],tolerance,half_scale)
        q=float(np.exp2(-np.asarray(errors)).mean());values.append(q)
        rows.append({'field':key,'actual':actual[key],'expected':expected[key],'normalized_errors':errors})
    return float(np.mean(values)),{'quantities':rows}


def closest_face(points,target):
    _,first=target.tree.query(points);indices=[];max_radius=float(target.radii.max())
    for point,initial in zip(points,first):
        upper=float(_distances_to_triangles(point,target.xyz[[initial]])[0])
        guard=64*np.finfo(float).eps*max(1.,float(np.abs(point).max()),upper,max_radius)
        ids=np.asarray(target.tree.query_ball_point(point,upper+max_radius+guard),int)
        lower=np.linalg.norm(target.centers[ids]-point,axis=1)-target.radii[ids]
        ids=ids[lower<=upper+guard]
        distances=_distances_to_triangles(point,target.xyz[ids]);indices.append(int(ids[np.argmin(distances)]))
    return np.asarray(indices,int)


def compare(baseline,candidate,contract,evidence,loader):
    base,cand,mapping=assignments(baseline,candidate);rows=[];values=[]
    settings=contract['protected_properties']
    for i,original in enumerate(base):
        if i not in mapping:
            rows.append({'baseline':original['object'],'candidate':None,'value':0.,'reason':'Export part absent'});values.append(0.);continue
        revised=cand[mapping[i]];a=loader(original['geometry']);b=loader(revised['geometry'])
        areas_a,areas_b=(triangle_areas(*mesh[:2]) for mesh in (a,b))
        used_a=np.unique(a[2][areas_a>0]);expected=[parameters(original,int(slot)) for slot in used_a]
        if not expected or areas_b.sum()<=0:
            rows.append({'baseline':original['object'],'candidate':revised['object'],'value':0.,'reason':'Assigned material surface absent'});values.append(0.);continue
        observations=[]
        if all(p==expected[0] for p in expected):
            # Unused slots and their names do not describe rendered appearance.
            for slot in np.unique(b[2][areas_b>0]):
                q,raw=parameter_score(parameters(revised,int(slot)),expected[0],settings['material_tolerance'],settings['material_half_scale'])
                fraction=float(areas_b[b[2]==slot].sum()/areas_b.sum())
                observations.append({'candidate_slot':int(slot),'surface_area_fraction':fraction,'value':q,**raw})
            method='uniform_actually_assigned_baseline_surface'
        else:
            # Genuine multiple-material parts use area samples and closest
            # full triangles in fixed coordinates, in both directions.
            directions=[]
            for side,(source,target,so,to) in enumerate(((a,b,original,revised),(b,a,revised,original))):
                points,faces=area_samples(*source[:2],32768,20261016+side)
                target_mesh=SurfaceMesh(*target[:2],surface_only=True)
                nearest=target_mesh.source_triangle_indices[closest_face(points,target_mesh)]
                pairs=np.c_[source[2][faces],target[2][nearest]];unique,counts=np.unique(pairs,axis=0,return_counts=True)
                groups=[]
                for (source_slot,target_slot),count in zip(unique,counts):
                    q,raw=parameter_score(parameters(so,int(source_slot)),parameters(to,int(target_slot)),
                        settings['material_tolerance'],settings['material_half_scale'])
                    groups.append({'source_slot':int(source_slot),'target_slot':int(target_slot),'samples':int(count),
                        'surface_area_fraction':float(count/len(points)),'value':q,**raw})
                directions.append({'direction':side,'samples':len(points),'groups':groups})
            observations=[{**r,'surface_area_fraction':r['surface_area_fraction']/2,'direction':d['direction']} for d in directions for r in d['groups']]
            method='bidirectional_fixed_world_surface_parameter_samples'
        if any(r['value'] is None for r in observations):
            return {'status':'technical_failure','reason':'Nonconstant assigned shader needs parameter sampling','parts':rows,'evidence':evidence}
        value=sum(r['value']*r['surface_area_fraction'] for r in observations);values.append(value)
        rows.append({'baseline':original['object'],'candidate':revised['object'],'baseline_used_slots':used_a.tolist(),
            'method':method,'value':value,'observations':observations})
    return {'status':'measured','preserved_fraction':float(np.mean(values)),'parts':rows,'evidence':evidence,
        'registration':'none','scope':'actually_assigned_export_representable_BSDF_parameters',
        'unassigned_material_policy':'both unassigned preserve assignment state; requested appearance is scored by semantic terms'}

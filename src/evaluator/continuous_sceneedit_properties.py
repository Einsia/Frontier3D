"""Preserve inherited scene data while allowing new editable target geometry."""
import numpy as np
from .continuous_scene_preservation import semantic,node_tree,deviation,object_structure,material,world_fixed,CAMERA_FIELDS

GROUPS=('structure','materials','cameras','lights','world','render_frame')


def measure(baseline,candidate,mesh_data,evidence):
    base={o['object']:o for o in baseline['objects']};cand={o['object']:o for o in candidate['objects']}
    if len(base)!=len(baseline['objects']) or len(cand)!=len(candidate['objects']):
        raise ValueError('Unique inherited source identities required')
    values={k:[] for k in GROUPS}
    for name,original in base.items():
        current=cand.get(name)
        if current is None or current['type']!=original['type']:
            missing={'object':name,'score':0.,'reason':'Original scene object absent or type changed'}
            values['structure'].append(missing)
            if original['type']=='CAMERA':values['cameras'].append(missing)
            if original['type']=='LIGHT':values['lights'].append(missing)
            if original['materials']:values['materials'].append(missing)
            continue
        a,b=object_structure(original),object_structure(current)
        if original['type'] in ('LIGHT','CAMERA'):
            a.pop('data_settings',None);b.pop('data_settings',None)
        values['structure'].append({'object':name,**deviation(a,b)})
        if original['type']!='CAMERA':
            values['structure'].append({'object':name,'quantity':'world_pose',
                **deviation(original['matrix_world'],current['matrix_world'])})
        if original.get('mesh'):
            values['structure'].append({'object':name,'quantity':'protected_native_mesh_data',**mesh_data(original,current)})
        before=[material(baseline['materials'].get(m)) for m in original['materials']]
        after=[material(candidate['materials'].get(m)) for m in current['materials']]
        if before or after:values['materials'].append({'object':name,**deviation(before,after)})
        if original['type']=='CAMERA':
            def camera(o):
                return {'projection':{k:o.get('settings',{}).get(k) for k in CAMERA_FIELDS},
                        'matrix_world':o['matrix_world'],'dof':semantic(o.get('dof'))}
            values['cameras'].append({'object':name,**deviation(camera(original),camera(current))})
        if original['type']=='LIGHT':
            def light(o):
                return {'settings':semantic(o['settings']),'nodes':node_tree(o['nodes']),
                        'matrix_world':o['matrix_world'],'visibility':o['visibility'],'parent':o['parent']}
            values['lights'].append({'object':name,**deviation(light(original),light(current))})
    extra_lights=sum(o['type']=='LIGHT' for name,o in cand.items() if name not in base)
    values['lights'].append({'quantity':'additional_lights','count':extra_lights,'score':2.**-extra_lights})
    values['structure'].append({'quantity':'unit_scale',**deviation(baseline['unit_scale'],candidate['unit_scale'])})
    values['world']=[deviation(world_fixed(baseline['world'],False),world_fixed(candidate['world'],False))]
    values['render_frame']=[deviation(semantic(baseline['render']),semantic(candidate['render'])),
        {'quantity':'saved_frame',**deviation(baseline['saved_frame'],candidate['saved_frame'],relative_half_scale=1.)}]
    # New drivers on an inherited owner are changes even if it had no driver.
    # Only explicitly identified new object/material owners are exempted.
    new_owners=[('Object',name) for name in cand.keys()-base.keys() if cand[name]['type']!='LIGHT']
    new_owners.extend(('Material',name) for name in candidate['materials'].keys()-baseline['materials'].keys())
    allowed_prefixes=tuple(kind+':'+name+':' for kind,name in new_owners)
    before=baseline['drivers']
    after={k:v for k,v in candidate['drivers'].items() if k in before or not k.startswith(allowed_prefixes)}
    values['structure'].append({'quantity':'inherited_drivers',**deviation(before,after)})
    groups={k:min((x['score'] for x in v),default=1.) for k,v in values.items()}
    return {'status':'measured','preserved_fraction':float(np.mean(list(groups.values()))),
        'groups':groups,'observations':values,'evidence':evidence,'registration':'none','physics_scoring':False,
        'group_policy':'six equally weighted property groups; worst required field within each group',
        'allowed_changes':['new editable target geometry and helpers','additional output cameras'],
        'identity_policy':'inherited source identities protected; new target names and mesh splits unrestricted'}

"""Continuous preservation of inherited L2 scene data with explicit edit scope."""
import copy
import math
import numpy as np

META={'use_fake_user','use_extra_user','is_runtime_data','tag'}
NODE_UI={'location','location_absolute','width','height','label','warning_propagation','use_custom_color','color',
         'select','show_options','show_preview','hide','show_texture'}
CAMERA_FIELDS=('type','sensor_fit','lens','sensor_width','sensor_height','ortho_scale','shift_x','shift_y',
               'clip_start','clip_end','panorama_type','fisheye_fov','fisheye_lens','latitude_min','latitude_max',
               'longitude_min','longitude_max','fisheye_polynomial_k0','fisheye_polynomial_k1',
               'fisheye_polynomial_k2','fisheye_polynomial_k3','fisheye_polynomial_k4')
GROUPS=('geometry','structure','materials','cameras','lights','world','render_frame')


def semantic(value,node_properties=False):
    if isinstance(value,dict):
        return {k:semantic(v) for k,v in value.items() if k not in META and
                not (node_properties and (k in NODE_UI or k.startswith('bl_')))}
    if isinstance(value,list):return [semantic(x) for x in value]
    return value


def node_tree(tree,allow=None):
    if tree is None:return None
    result=copy.deepcopy(tree)
    for name,node in result.get('nodes',{}).items():
        node['properties']=semantic(node['properties'],True)
        if allow=='light' and node['type']=='ShaderNodeEmission':
            node['inputs']=[p for p in node['inputs'] if p[0] not in ('Color','Strength')]
        if allow=='world_strength' and node['type']=='ShaderNodeBackground':
            node['inputs']=[p for p in node['inputs'] if p[0]!='Strength']
        if 'group' in node:node['group']=node_tree(node['group'],allow)
    return semantic(result)


def deviation(expected,actual,*,relative_half_scale=.01,precision=1e-6):
    """Worst required field deviation; extra defaults cannot dilute an edit.

    Real scalar values use a continuous kernel. Categorical identities use
    exact equality. The complete source observations stay separately bound.
    """
    rows=[];count=0
    def visit(a,b,path):
        nonlocal count
        if isinstance(a,dict) and isinstance(b,dict):
            for k in sorted(a.keys()|b.keys()):
                if k not in a or k not in b:
                    rows.append({'field':path+'/'+k,'score':0.,'reason':'Required field added or removed'});count+=1
                else:visit(a[k],b[k],path+'/'+k)
        elif isinstance(a,list) and isinstance(b,list):
            if len(a)!=len(b):
                rows.append({'field':path,'score':0.,'reason':'Required population changed','before_count':len(a),'after_count':len(b)});count+=1
            else:
                for i,(x,y) in enumerate(zip(a,b)):visit(x,y,path+'/'+str(i))
        elif isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool):
            count+=1
            if not math.isfinite(a) or not math.isfinite(b):raise ValueError('Non-finite unclassified property')
            scale=relative_half_scale*max(abs(a),1.)
            error=max(abs(a-b)-precision*max(abs(a),1.),0.)/scale
            if error:rows.append({'field':path,'score':2.**-error,'normalized_error':error,
                'expected':a,'actual':b,'half_scale':scale,'precision':precision*max(abs(a),1.)})
        else:
            count+=1
            if a!=b:rows.append({'field':path,'score':0.,'expected':a,'actual':b,'reason':'Categorical identity changed'})
    visit(expected,actual,'')
    return {'score':min((r['score'] for r in rows),default=1.),'observed_fields':count,'deviations':rows,
            'aggregation':'worst required scalar/category, numeric 2**(-error); no score bins'}


def object_structure(obj):
    result={k:obj.get(k) for k in ('type','parent','parent_type','parent_bone','collections','visibility',
        'editable','modifiers','constraints','particles','rig','splines','data_settings','vertex_groups')}
    result['mesh_metadata']={k:v for k,v in obj['mesh'].items() if k!='payload'} if obj.get('mesh') else None
    return semantic(result)


def world_fixed(world,allow_strength):
    if world is None:return None
    return {'settings':semantic(world['settings']),'nodes':node_tree(world['nodes'],'world_strength' if allow_strength else None)}


def light_fixed(obj):
    return {'settings':semantic({k:v for k,v in obj['settings'].items() if k not in ('color','energy')}),
            'nodes':node_tree(obj['nodes'],'light'),'matrix_world':obj['matrix_world'],
            'visibility':obj['visibility'],'parent':obj['parent']}


def material(value):
    if value is None:return None
    return {'settings':semantic(value['settings']),'nodes':node_tree(value['nodes'])}


def measure(baseline,candidate,task_number,geometry,evidence):
    if task_number not in ('003','005'):raise ValueError('Lighting edit scope required')
    base={o['object']:o for o in baseline['objects']};cand={o['object']:o for o in candidate['objects']}
    if len(base)!=len(baseline['objects']) or len(cand)!=len(candidate['objects']):raise ValueError('Source objects must be unique; evaluated instances belong to separate geometry proof')
    values={key:[] for key in GROUPS};values['geometry']=[geometry]
    for name,original in base.items():
        if name not in cand:
            values['structure'].append({'object':name,'score':0.,'reason':'Original scene object absent'})
            if original['type']=='CAMERA':values['cameras'].append({'object':name,'score':0.,'reason':'Original camera absent'})
            if original['type']=='LIGHT':values['lights'].append({'object':name,'score':0.,'reason':'Original light absent'})
            if original['materials']:values['materials'].append({'object':name,'score':0.,'reason':'Original material surface absent'})
            continue
        current=cand[name]
        if original['type']!=current['type']:
            failure={'object':name,'score':0.,'reason':'Required inherited object type changed'}
            values['structure'].append(failure)
            if original['type']=='LIGHT':values['lights'].append(failure)
            if original['type']=='CAMERA':values['cameras'].append(failure)
            if original['materials']:values['materials'].append(failure)
            continue
        a,b=object_structure(original),object_structure(current)
        # Camera/light intrinsic parameters have explicit groups and edits.
        if original['type'] in ('LIGHT','CAMERA'):
            a.pop('data_settings',None);b.pop('data_settings',None)
        values['structure'].append({'object':name,**deviation(a,b)})
        if original['type']!='CAMERA':
            values['structure'].append({'object':name,'quantity':'world_pose',
                **deviation(original['matrix_world'],current['matrix_world'])})
        before=[material(baseline['materials'].get(m)) for m in original['materials']]
        after=[material(candidate['materials'].get(m)) for m in current['materials']]
        if before or after:values['materials'].append({'object':name,**deviation(before,after)})
        if original['type']=='CAMERA':
            def camera(o):return {'projection':{k:o.get('settings',{}).get(k) for k in CAMERA_FIELDS},
                                  'matrix_world':o['matrix_world'],'dof':semantic(o.get('dof'))}
            values['cameras'].append({'object':name,**deviation(camera(original),camera(current))})
        if original['type']=='LIGHT':values['lights'].append({'object':name,**deviation(light_fixed(original),light_fixed(current))})
    extras=[o for name,o in cand.items() if name not in base and o['type']!='CAMERA']
    values['structure'].append({'quantity':'additional_non_camera_objects','score':2.**-len(extras),'count':len(extras)})
    values['lights'].append({'quantity':'additional_lights','score':2.**-sum(o['type']=='LIGHT' for o in extras),
                             'count':sum(o['type']=='LIGHT' for o in extras)})
    values['world']=[deviation(world_fixed(baseline['world'],task_number=='005'),world_fixed(candidate['world'],task_number=='005'))]
    values['render_frame']=[deviation(semantic(baseline['render']),semantic(candidate['render'])),
        {'quantity':'saved_frame',**deviation(baseline['saved_frame'],candidate['saved_frame'],relative_half_scale=1.)},
        {'quantity':'drivers',**deviation(baseline['drivers'],candidate['drivers'])}]
    groups={key:min((x['score'] for x in rows),default=1.) for key,rows in values.items()}
    return {'status':'measured','preserved_fraction':float(np.mean(list(groups.values()))),'groups':groups,
        'observations':values,'evidence':evidence,'registration':'none','physics_scoring':False,
        'group_policy':'seven fixed equally weighted property groups; worst required deviation inside each group',
        'allowed_changes':['existing_light_color','existing_light_energy','additional_output_cameras']+
            (['existing_world_background_strength'] if task_number=='005' else []),
        'identity_policy':'inherited original source-object identities; evaluated instances checked as a full multiset'}

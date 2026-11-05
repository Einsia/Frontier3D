"""Public contract and evaluator-owned local action plans (centimetres)."""
from __future__ import annotations
import hashlib, json, math, re
from pathlib import Path
DOORS = ['house01.door','house02.door','smithy01.door','storehouse.door','pen.gate']
CHESTS = ['house01.chest','storehouse.chest']
CROPS = [f'farm.crop{i:02}' for i in range(1,7)]
BLOCKS = [f'edit.block{i:02}' for i in range(1,4)]
FURNACES = ['smithy01.furnace']
REQUIRED = DOORS + CHESTS + CROPS + BLOCKS + FURNACES
BUILDINGS = [f'building.house{i:02}' for i in range(1,9)] + ['building.smithy01','building.smithy02','building.storehouse']
VIEWS = ['overview','street','interior','farm','smithy','waterfront']


def read_json(p: Path):
    return json.loads(p.read_bytes())


def write_json(p: Path, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def digest(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_digest(p: Path):
    h=hashlib.sha256()
    for f in sorted(p.rglob('*')):
        if f.is_symlink(): raise ValueError(f'Symlink forbidden: {f}')
        if f.is_file() and not set(f.relative_to(p).parts) & {'Binaries','Intermediate','Saved','DerivedDataCache'}:
            h.update(f.relative_to(p).as_posix().encode()+b'\0'+f.read_bytes()+b'\0')
    return h.hexdigest()


def vector(v):
    if not isinstance(v,list) or len(v)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>1e7 for n in v):
        raise ValueError(f'Invalid finite cm vector: {v!r}')
    return v


def validate_entity_binding(key, e):
    for k in ['approach_cm','look_cm']: vector(e[k])
    if key in DOORS:
        for k in ['crossing_from_cm','crossing_to_cm']: vector(e[k])
        if not 150 <= math.dist(e['crossing_from_cm'],e['crossing_to_cm']) <= 300:
            raise ValueError(f'{key}: crossing must span 150–300 cm')


def validate_journey(journey):
    if not 4 <= len(journey) <= 12: raise ValueError('journey needs 4–12 segments')
    for s in journey:
        vector(s['direction'])
        if not .2 <= s['seconds'] <= 15: raise ValueError('invalid journey duration')


def validate_bindings(b):
    if b.get('version') != 1: raise ValueError('bindings version must be 1')
    for key in REQUIRED: validate_entity_binding(key, b['entities'][key])
    for key in VIEWS:
        for k in ['position_cm','look_cm']: vector(b['views'][key][k])
    validate_journey(b['journey'])
    return b


def validate_plan(p):
    if p.get('kind') not in {'local','views','journey','e2e'}: raise ValueError('unknown plan kind')
    steps=p.get('steps',[])
    if not 1 <= len(steps) <= 2000: raise ValueError('invalid step count')
    names=set()
    for s in steps:
        name=s.get('name','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',name) or name in names or name in {'initial','final','completed','error'} or name.startswith('trajectory_'):
            raise ValueError('unsafe, reserved or duplicate step name')
        names.add(name)
        op=s['op']
        if op not in {'fixture','look','look_entity','interact','probe','move','wait','snapshot','capture','camera','walk_to','invoke','inspect','ray','export_geometry','instance_masks'}:
            raise ValueError('unknown operation')
        if op in {'ray','export_geometry'} and p['kind']!='views': raise ValueError('Geometry measurement is views-only')
        if op=='instance_masks':
            if p['kind']!='views':raise ValueError('Instance masks are views-only')
            groups=s.get('groups',[])
            if not groups or len({g['id'] for g in groups})!=len(groups):raise ValueError('Unique mask groups required')
            colors=[];actors=[]
            for group in groups:
                color=group['rgb']
                if len(color)!=3 or any(type(v) is not int or not 0<=v<=255 for v in color) or not any(color):raise ValueError('Invalid mask color')
                colors.append(tuple(color));actors+=group['actors']
            if len(set(colors))!=len(colors) or len(set(actors))!=len(actors):raise ValueError('Mask colors/actors must be unique')
        if op=='camera' and not 20<=s.get('horizontal_fov_deg',90)<=120:raise ValueError('Invalid horizontal FOV')
        if op=='inspect' and (p['kind']!='views' or s.get('target') not in BUILDINGS or s.get('view') not in {'interior','exterior'}): raise ValueError('Invalid component camera')
        if op=='invoke' and p['kind']!='local': raise ValueError('Direct fault injection is local-only')
        if op=='fixture' and (p['kind']!='local' or s.get('purpose')!='local_test_setup'):
            raise ValueError('teleport is forbidden outside local fixtures')
        for key in {'fixture':['position_cm'],'look':['target_cm'],'camera':['position_cm','target_cm'],
                    'ray':['from_cm','to_cm'],'probe':['from_cm','to_cm'],'move':['direction'],'walk_to':['target_cm']}.get(op,[]): vector(s[key])
        if op in {'move','wait','walk_to'} and not 0 < s.get('seconds',0) <= 30: raise ValueError('invalid duration')
        if op in {'interact','look_entity','invoke'} and s.get('target') not in REQUIRED: raise ValueError('unknown target')
        if op in {'interact','invoke'} and s.get('action') not in {'use','take','harvest','plant','remove','place','process'}: raise ValueError('unknown action')
    if p['kind']=='e2e' and not any(s['op']=='interact' for s in steps): raise ValueError('e2e must contain interactions')
    return p


def local_plan(entity, binding):
    steps=[]
    def add(op,name,**kw): steps.append(dict(op=op,name=name,**kw))
    add('fixture','setup',purpose='local_test_setup',position_cm=binding['approach_cm'])
    add('look','aim',target_cm=binding['look_cm']); add('wait','settle',seconds=.5)
    add('snapshot','before');add('capture','before_view')
    def probe(name): add('probe',name,from_cm=binding['crossing_from_cm'],to_cm=binding['crossing_to_cm'])
    if entity in DOORS: probe('closed_probe')
    actions = ['use','use','use'] if entity in DOORS else (
        ['use','take','take','use'] if entity in CHESTS else
        ['harvest','harvest','plant'] if entity in CROPS else
        ['remove','remove','place'] if entity in BLOCKS else ['process','process'])
    for i,action in enumerate(actions,1):
        # Removed blocks/crops may legitimately no longer be ray targets.
        if entity in DOORS+CHESTS: add('look_entity',f'aim_{i}',target=entity)
        add('interact',f'action_{i}',target=entity,action=action)
        if i==1 and entity in DOORS+CHESTS:
            add('wait','motion_wait_1',seconds=.2);add('capture','motion_view_1')
            add('wait',f'wait_{i}',seconds=1.3)
        else:add('wait',f'wait_{i}',seconds=1.5)
        add('snapshot',f'after_{i}');add('capture',f'view_{i}')
        if entity in DOORS: probe(f'probe_{i}')
    if entity in DOORS:
        add('fixture','cross_setup',purpose='local_test_setup',position_cm=binding['crossing_from_cm'])
        add('walk_to','cross_walk',target_cm=binding['crossing_to_cm'],seconds=5)
        add('snapshot','crossed')
    far=list(binding['approach_cm']);far[0]+=1200
    add('fixture','far_setup',purpose='local_test_setup',position_cm=far)
    add('look_entity','far_aim',target=entity); add('snapshot','far_before')
    add('invoke','far_action',target=entity,action=actions[0]);add('wait','far_wait',seconds=1.5)
    add('snapshot','far_after')
    # Fresh-state negative call: harvest must still be applicable to the mature crop.
    far_steps=[s for s in steps if s['name'].startswith('far_')]
    steps=far_steps+[s for s in steps if not s['name'].startswith('far_')]
    return validate_plan({'version':1,'kind':'local','target':entity,'steps':steps})


def views_plan(bindings):
    steps=[dict(op='export_geometry',name='scene_geometry')]
    for view in VIEWS:
        v=bindings['views'][view]
        steps += [dict(op='camera',name=view+'_camera',position_cm=v['position_cm'],target_cm=v['look_cm']),
                  dict(op='wait',name=view+'_settle',seconds=1),dict(op='capture',name=view)]
    for i,building in enumerate(BUILDINGS):
        for suffix,yaw in [('exterior',0),('interior0',0),('interior90',90),('interior180',180),('interior270',270)]:
            key=f'building_{i:02}_{suffix}'
            steps += [dict(op='inspect',name=key+'_camera',target=building,view='exterior' if suffix=='exterior' else 'interior',yaw=yaw),
                      dict(op='wait',name=key+'_settle',seconds=.5),dict(op='capture',name=key)]
    return validate_plan(dict(kind='views',steps=steps))


def journey_plan(bindings):
    validate_journey(bindings['journey'])
    steps=[dict(op='move',name=f'walk_{i}',direction=s['direction'],seconds=s['seconds'])
           for i,s in enumerate(bindings['journey'])]
    steps.append(dict(op='snapshot',name='journey_end'))
    return validate_plan(dict(kind='journey',steps=steps))


def make_plans(bindings, *, failures=None):
    # Strict public validation remains the default. Evaluators may collect each
    # invalid submission section while measuring independent valid sections.
    if failures is None: validate_bindings(bindings)
    if bindings.get('version') != 1: raise ValueError('bindings version must be 1')
    plans={}
    def collect(key, build):
        try: plans[key]=build()
        except (KeyError, TypeError, ValueError) as error:
            if failures is None: raise
            failures[key]={'status':'submission_contract_failure','error':str(error),'measured':False}
    # Capture visual evidence before interactive episodes.
    collect('views', lambda: views_plan(bindings))
    for entity in REQUIRED:
        def build(entity=entity):
            binding=bindings['entities'][entity]
            validate_entity_binding(entity,binding)
            return local_plan(entity,binding)
        collect(entity.replace('.','_'),build)
    collect('journey', lambda: journey_plan(bindings))
    return plans


def reference_plan(bindings):
    """The candidate predicts one camera; the evaluator renders RGB and ID evidence."""
    view=bindings['views']['overview']
    colors=[[240,40,40],[40,220,40],[40,40,240],[230,210,40],[220,40,220],[40,210,220],
            [240,130,40],[130,40,240],[40,130,70],[130,210,240],[220,120,160]]
    groups=[]
    for name,rgb in zip(BUILDINGS,colors):
        alias=name.removeprefix('building.')
        actors=[name]+[key for key in DOORS+CHESTS+FURNACES if key.startswith(alias+'.')]
        groups.append(dict(id=name,actors=actors,rgb=rgb,**{'class':'building'}))
    return validate_plan({'version':1,'kind':'views','render_size':[2560,1440],
        'camera_protocol':'joint_scene_camera_prediction','steps':[
        dict(op='camera',name='reference_camera',position_cm=view['position_cm'],target_cm=view['look_cm'],horizontal_fov_deg=view.get('horizontal_fov_deg',90)),
        dict(op='wait',name='reference_settle',seconds=2),dict(op='snapshot',name='reference_pose'),
        dict(op='capture',name='reference_rgb'),dict(op='instance_masks',name='reference_ids',groups=groups),
        dict(op='wait',name='mask_settle',seconds=1),dict(op='snapshot',name='mask_pose'),dict(op='capture',name='reference_mask')]})

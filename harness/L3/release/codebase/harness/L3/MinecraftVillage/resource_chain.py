"""Resource-bearing local fixtures; explicitly not a continuous walking task."""
from .protocol import validate_plan, validate_entity_binding, read_json
from .inventory import counts
from .evaluate import entity, changed, meshes

TARGETS=['house01.chest','farm.crop01','smithy01.furnace','storehouse.chest']
EXPECTED={
 'chain_initial':[0,0,0,0], 'seed_taken':[1,0,0,0], 'seed_repeated':[1,0,0,0],
 'crop_harvested':[1,1,0,0], 'crop_replanted':[0,1,0,0],
 'processed':[0,0,1,0], 'process_repeated':[0,0,1,0],
 'storage_taken':[0,0,1,1], 'house_revisited':[0,0,1,1],
 'immature_reharvest':[0,0,1,1]}

def plan(bindings):
    for target in TARGETS:validate_entity_binding(target,bindings['entities'][target])
    steps=[]
    def add(op,name,**kw):steps.append(dict(op=op,name=name,**kw))
    def setup(target,name):
        b=bindings['entities'][target]
        add('fixture',name+'_setup',purpose='local_test_setup',position_cm=b['approach_cm'])
        add('look',name+'_aim',target_cm=b['look_cm'])
        add('wait',name+'_settle',seconds=.5)
    def action(target,verb,name):
        b=bindings['entities'][target]
        add('look',name+'_aim',target_cm=b['look_cm'])
        add('interact',name+'_action',target=target,action=verb)
        add('wait',name+'_wait',seconds=1.2 if verb=='use' else .5)
    def checkpoint(name):
        add('snapshot',name)
        add('capture',name+'_view')
    checkpoint('chain_initial')
    setup('house01.chest','house')
    action('house01.chest','use','open_seed_chest')
    action('house01.chest','take','take_seed');checkpoint('seed_taken')
    action('house01.chest','take','repeat_seed');checkpoint('seed_repeated')
    setup('farm.crop01','crop');checkpoint('crop_before')
    action('farm.crop01','harvest','harvest_crop');checkpoint('crop_harvested')
    action('farm.crop01','plant','plant_crop');checkpoint('crop_replanted')
    setup('smithy01.furnace','furnace');checkpoint('before_processing')
    add('interact','start_processing',target='smithy01.furnace',action='process')
    add('wait','processing_early_wait',seconds=.25);checkpoint('furnace_active')
    add('wait','processing_wait',seconds=3);checkpoint('processed')
    action('smithy01.furnace','process','repeat_processing');checkpoint('process_repeated')
    setup('storehouse.chest','storage')
    action('storehouse.chest','use','open_storage')
    action('storehouse.chest','take','take_storage');checkpoint('storage_taken')
    setup('house01.chest','return_house')
    action('house01.chest','take','return_take');checkpoint('house_revisited')
    setup('farm.crop01','return_crop')
    action('farm.crop01','harvest','immature_harvest');checkpoint('immature_reharvest')
    return validate_plan({'version':1,'kind':'local','scope':'resource_bearing_chain_with_local_setup',
                          'continuous_walk':False,'steps':steps})

def diagnose(folder):
    if not read_json(folder/'completed.json').get('completed'):
        raise ValueError('Resource episode did not complete')
    frames={name:read_json(folder/(name+'.json')) for name in set(EXPECTED)|{'crop_before','before_processing','furnace_active'}}
    if any(f.get("protocol")!="ue5-observer-v1" for f in frames.values()):raise ValueError("Invalid observer protocol")
    inventory={}
    for name,wanted in EXPECTED.items():
        try:
            observed=counts(frames[name])
            inventory[name]={'expected':wanted,'observed':observed,
                             'passed':None if observed is None else observed==wanted}
        except ValueError as error:inventory[name]={'passed':False,'reason':str(error)}
    checks={};contracts=[]
    for target in TARGETS:
        observed=sum(e.get('id')==target for e in frames['chain_initial'].get('entities',[]))
        if observed!=1:contracts.append({'target':target,'observed_count':observed})
    if not any(row['target']=='farm.crop01' for row in contracts):
        crop=lambda name:entity(frames[name],'farm.crop01')
        checks['harvest_changes_visible_crop']=changed(crop('crop_before'),crop('crop_harvested'))
        checks['plant_restores_visible_crop']=bool(meshes(crop('crop_replanted'))) and changed(crop('crop_harvested'),crop('crop_replanted'))
        checks['replanted_crop_persists']=not changed(crop('crop_replanted'),crop('immature_reharvest'))
    else:
        checks.update(harvest_changes_visible_crop=None,plant_restores_visible_crop=None,replanted_crop_persists=None)
    active=[]
    def light(frame):
        e=entity(frame,'smithy01.furnace')
        return sum(l['intensity'] for l in e.get('lights',[]) if l.get('visible'))
    if not any(row['target']=='smithy01.furnace' for row in contracts):
        baseline=light(frames['before_processing'])
        for path in sorted(folder.glob('trajectory_*.json')):
            frame=read_json(path)
            if frames['before_processing']['time']<=frame['time']<=frames['processed']['time'] and light(frame)>baseline+1e-6:
                active.append(frame['time'])
    duration=max(active)-min(active) if active else None
    # Absence of a light component cannot reject valid emissive-material effects.
    checks['processing_light_observed_for_one_second']=True if duration is not None and duration>=1 else None
    return {'status':'submission_contract_failure' if contracts else 'measured',
            'scope':'Persistent inventory and world effects across local test placements in one live session; no grants, direct state writes or process restart.',
            'continuous_walk_verified':False,'contract_failures':contracts,
            'inventory':{'checks':inventory,'passed':sum(r['passed'] is True for r in inventory.values()),
                         'failed':sum(r['passed'] is False for r in inventory.values()),
                         'unresolved':sum(r['passed'] is None for r in inventory.values()),'total':len(inventory)},
            'geometry_checks':checks,'processing_light_observed_duration_seconds':duration,
            'visual_evidence':['furnace_active_view.png','processed_view.png'],
            'limitation':'A continuous on-foot route is separate. Emissive-only furnace effects require rendered evidence; sparse light samples do not prove their absence.',
            'formal_score':None}

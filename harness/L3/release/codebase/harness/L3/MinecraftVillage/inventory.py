"""Evaluate the public inventory primitive; never read candidate semantic strings."""
import math
from .protocol import DOORS, CHESTS, CROPS, BLOCKS, read_json

ITEMS=('seeds','crops','processed','tools')


def counts(frame):
    observations=frame.get('trusted_inventory')
    if observations is None:return None
    if len(observations)!=1:raise ValueError('Exactly one runtime inventory is required')
    values=observations[0]['counts']
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 or v!=int(v) for v in values.values()):raise ValueError('Invalid inventory count')
    if any(v for k,v in values.items() if k not in ITEMS):raise ValueError('Unexpected inventory item')
    return [int(values.get(k,0)) for k in ITEMS]


def local(folder,target,required=True):
    if not required:return {'status':'not_in_fixture_contract','checks':{},'value':None}
    zero=[0,0,0,0]
    expected={'far_before':zero,'far_after':zero,'before':zero}
    if target in CHESTS:
        acquired=[1,0,0,0] if target=='house01.chest' else [0,0,0,1]
        expected.update(after_1=zero,after_2=acquired,after_3=acquired,after_4=acquired)
    elif target in CROPS:expected.update(after_1=[0,1,0,0],after_2=[0,1,0,0],after_3=[0,1,0,0])
    elif target in DOORS+BLOCKS:expected.update(after_1=zero,after_2=zero,after_3=zero)
    else:expected.update(after_1=zero,after_2=zero)
    rows={}
    for name,wanted in expected.items():
        path=folder/(name+'.json')
        if not path.exists():rows[name]={'passed':None,'reason':'Missing runtime observation'};continue
        try:
            observed=counts(read_json(path))
            rows[name]={'expected':wanted,'observed':observed,'passed':None if observed is None else observed==wanted}
        except ValueError as error:rows[name]={'passed':False,'reason':str(error)}
    return {'status':'measured' if all(r['passed'] is not None for r in rows.values()) else 'partial',
            'checks':rows,'passed':sum(r['passed'] is True for r in rows.values()),'total':len(rows),
            'unresolved':sum(r['passed'] is None for r in rows.values()),'value':None,
            'scope':'Fresh-session local positive/negative inventory checks; the continuous task chain is reported separately.'}

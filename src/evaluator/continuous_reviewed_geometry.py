"""Transfer a reviewed semantic region only across an identical geometry inventory."""
from collections import Counter, defaultdict


def select(primary, current, annotation):
    if primary['scene']['sha256']!=annotation['scene_sha256']:
        raise ValueError('Primary scene lacks a matching semantic review')
    if len(primary['snapshots'])!=1 or len(current['snapshots'])!=1:
        raise ValueError('This review covers one static frame only')
    if primary['snapshots'][0]['frame']!=current['snapshots'][0]['frame']:
        raise ValueError('Reviewed frame differs')
    a=[o for o in primary['snapshots'][0]['objects'] if o.get('geometry')]
    b=[o for o in current['snapshots'][0]['objects'] if o.get('geometry')]
    inventory=lambda rows:Counter(o['geometry']['sha256'] for o in rows)
    if inventory(a)!=inventory(b):
        raise ValueError('Complete geometry inventory differs; additional semantic review required')
    names=annotation['objects']
    if len(names)!=len(set(names)):raise ValueError('Duplicate reviewed locator')
    selected=[]
    for name in names:
        matches=[o for o in a if o['object']==name]
        if len(matches)!=1:raise ValueError('Reviewed locator is absent or ambiguous: '+name)
        selected.append(matches[0]['geometry'])
    by_hash=defaultdict(list)
    for obj in b:by_hash[obj['geometry']['sha256']].append(obj['geometry'])
    result=[by_hash[p['sha256']].pop() for p in selected]
    return result,{'method':'Complete evaluated geometry SHA-256 multiset equality, preserving duplicate instances',
        'complete_scene_geometry_equal':True,'primary_geometry':selected,'current_geometry':result,
        'annotated_scene_sha256':annotation['scene_sha256'],'geometry_instances_checked':len(a)}

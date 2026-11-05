"""Case review artifacts using existing L2 scene and paired-image methods."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .l2_diagnostics import write_diagnostics
from .l2_requirements import digest
from .l2_visual import annotation_template,visual_diagnostics


def prepare_case_review(evidence,report,policy,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    measured={**evidence,'scene':{**evidence.get('scene',{}),'objects':{n:dict(o) for n,o in evidence.get('scene',{}).get('objects',{}).items()}}}
    # Untagged meshes still appear in diagnostics. This is explicitly not classification.
    objects=measured.get('scene',{}).get('objects',{})
    for name,obj in objects.items():
        if obj.get('type')=='MESH' and not obj.get('role'):
            obj['role']='unclassified'
            owner=name;visited=set()
            while objects.get(owner,{}).get('parent') in objects and owner not in visited:
                visited.add(owner);owner=objects[owner]['parent']
            obj['entity']=owner
    # Dense scans remain useful as inventories without pretending a truncated graph is complete.
    meshes=sum(o.get('type')=='MESH' for o in objects.values())
    if meshes<=200:
        diagnostics=write_diagnostics(measured,directory)
    else:
        from .l2_diagnostics import scene_diagnostics,draw_scene
        diagnostics=scene_diagnostics(measured,include_support=False)
        diagnostics['support']={'status':'not_measurable','reason':'More than 200 meshes; support grouping needs reviewed entity annotations'}
        draw_scene(diagnostics,directory/'scene_diagnostics.png')
        (directory/'scene_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n')
    annotations=annotation_template(evidence)
    visual_diagnostics(annotations,directory/'visual')
    (directory/'annotations.template.json').write_text(json.dumps(annotations,ensure_ascii=False,indent=2)+'\n')
    from .l2_visual import image_ref
    files={str(p.resolve()):image_ref(p)['sha256'] for p in directory.rglob('*') if p.is_file()}
    for items in (evidence.get('artifacts',{}),evidence.get('reference_images',{})):
        for item in items.values():
            if item.get('path') and item.get('sha256'):
                files[item['path']]=item['sha256']
    for obj in evidence.get('scene',{}).get('objects',{}).values():
        full=obj.get('geometry_evidence',{})
        if full.get('full_geometry_file') and evidence.get('geometry_root'):
            ref=image_ref(Path(evidence['geometry_root'])/full['full_geometry_file'])
            if ref['sha256']!=full['full_geometry_sha256']:raise ValueError('Full geometry changed before review')
            files[ref['path']]=ref['sha256']
    packet={'protocol':'l2-case-review-v1','task_id':policy['task_id'],'case_policy_sha256':digest(policy),
        'report':image_ref(report['report_path']),'evidence':image_ref(report['evidence_path']),
        'files_sha256':files,'questions':[] if policy.get('scoring_profile') else [r for r in policy['requirements'] if r['implementation']!='complete'],
        'status':'pending_human','note':'Proxy measurements and candidate labels are not reviewed semantics. No automatic approval.'}
    (directory/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
    response={'packet_sha256':digest(packet),'reviewer':'','reviewed_at':'',
        'decisions':{q['id']:{'decision':'pending','rationale':'','evidence_paths':[]} for q in packet['questions']}}
    (directory/'response.template.json').write_text(json.dumps(response,ensure_ascii=False,indent=2)+'\n')
    return packet

"""Audit actual UE material/texture references against the organizer's import manifest."""
from pathlib import Path
from .protocol import digest


def audit(geometry, imported, project=None, initial_hashes=None):
    catalog=geometry.get('material_catalog')
    if catalog is None:return {'status':'missing_runtime_material_evidence','value':None}
    assigned={m for instance in geometry['instances'] if instance.get('visible',True) for m in instance.get('materials',[]) if m}
    bases={catalog[m]['base_material'] for m in assigned if m in catalog}
    textures={t for m in assigned if m in catalog for t in catalog[m]['texture_assets']}
    rows=[]
    for asset in imported['assets']:
        paths=[asset['texture']] if 'texture' in asset else [x['object_path'] for x in asset.get('textures',{}).values()]
        used=[p for p in paths if p in textures]
        hashes={}
        if project is not None and initial_hashes is not None:
            for p in used:
                relative='Content/'+p.split('.',1)[0].removeprefix('/Game/')+'.uasset'
                file=Path(project)/relative
                expected=initial_hashes.get('project/'+relative)
                hashes[p]=bool(expected and file.is_file() and digest(file)==expected)
        rows.append({'id':asset['id'],'assigned_base_material':asset['material'] in bases,
                     'referenced_textures':used,'texture_bytes_match_preloaded_assets':hashes,
                     'used_by_exported_materials':bool(used)})
    return {'status':'measured','imported_materials':len(rows),'used_materials':sum(r['used_by_exported_materials'] for r in rows),
            'materials':rows,'unassigned_material_slots':sum(not m for i in geometry['instances'] if i.get('visible',True) for m in i.get('materials',[])),
            'unresolved_material_references':sorted(assigned-set(catalog)),
            'scope':'Engine-observed assignments and texture dependencies. Unchanged texture asset hashes substantiate pack provenance; modified assets retain a separate flag. This is not an aesthetic score or a guarantee that every assigned slot is visible in the image.'}

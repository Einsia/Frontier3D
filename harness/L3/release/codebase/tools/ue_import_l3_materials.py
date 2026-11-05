"""Run inside UE Python commandlet, with L3_MATERIAL_IMPORT=config.json.

Config: {"manifest": "/assets/manifest.json", "ids": ["wood_planks"],
         "report": "/workspace/import-report.json"}.
Only material/texture assets are created; there is no scene layout or gameplay.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import unreal

def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle,'sha256').hexdigest()

def main():
    config=json.loads(Path(os.environ['L3_MATERIAL_IMPORT']).read_text())
    manifest=Path(config['manifest']).resolve()
    pack=json.loads(manifest.read_text())
    if pack.get('status') != 'complete':
        raise ValueError('Only a completed, checksummed pack may be imported')
    catalog={a['id']:a for a in pack['assets']}
    records={f['path']:f for f in pack['files']}
    ids=config['ids']
    if not ids or len(ids)!=len(set(ids)) or any(x not in catalog for x in ids):
        raise ValueError('ids must be a nonempty unique subset of the catalog')
    tools=unreal.AssetToolsHelpers.get_asset_tools()
    library=unreal.MaterialEditingLibrary
    properties={'basecolor':unreal.MaterialProperty.MP_BASE_COLOR,
                'normal':unreal.MaterialProperty.MP_NORMAL,
                'roughness':unreal.MaterialProperty.MP_ROUGHNESS,
                'metallic':unreal.MaterialProperty.MP_METALLIC,
                'ao':unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
                'opacity':unreal.MaterialProperty.MP_OPACITY_MASK}
    report={'pack_sha256':sha(manifest),'engine':unreal.SystemLibrary.get_engine_version(),'assets':[]}
    for asset_id in ids:
        if not re.fullmatch(r'[A-Za-z0-9_]+',asset_id):
            raise ValueError('invalid asset ID')
        asset=catalog[asset_id]
        destination='/Game/L3Materials/'+asset_id
        material_name='M_'+asset_id
        if unreal.EditorAssetLibrary.does_asset_exist(destination+'/'+material_name):
            raise ValueError('Refusing to overwrite an existing material: '+asset_id)
        # Validate all source files before importing any part of this material.
        for entry in asset['maps'].values():
            path=manifest.parent/entry['path']
            path.resolve().relative_to(manifest.parent)
            if path.is_symlink() or sha(path)!=records[entry['path']]['sha256']:
                raise ValueError('Texture checksum mismatch: '+entry['path'])
        material=tools.create_asset(material_name,destination,unreal.Material,unreal.MaterialFactoryNew())
        if material is None:
            raise RuntimeError('Material creation failed: '+asset_id)
        material.set_editor_property('used_with_instanced_static_meshes',True)
        if 'opacity' in asset['maps']:
            material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_MASKED)
        imported={}
        for channel,entry in asset['maps'].items():
            if channel not in properties:
                continue
            task=unreal.AssetImportTask()
            task.filename=str(manifest.parent/entry['path'])
            task.destination_path=destination
            task.destination_name='T_'+asset_id+'_'+channel
            task.automated=True; task.replace_existing=False; task.save=False
            tools.import_asset_tasks([task])
            paths=list(task.imported_object_paths)
            if len(paths)!=1:
                raise RuntimeError('Expected one imported texture: '+entry['path'])
            texture=unreal.load_asset(paths[0])
            texture.set_editor_property('srgb',channel=='basecolor')
            if channel=='normal':
                texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_NORMALMAP)
                texture.set_editor_property('flip_green_channel',entry['normal_convention']=='OpenGL')
                sampler=unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL
            elif channel=='basecolor':
                texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_DEFAULT)
                sampler=unreal.MaterialSamplerType.SAMPLERTYPE_COLOR
            else:
                texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_MASKS)
                sampler=unreal.MaterialSamplerType.SAMPLERTYPE_MASKS
            if not unreal.EditorAssetLibrary.save_loaded_asset(texture):
                raise RuntimeError('Failed saving texture: '+entry['path'])
            imported[channel]={'object_path':texture.get_path_name(),'srgb':bool(texture.get_editor_property('srgb'))}
            if channel in properties:
                expression=library.create_material_expression(material,unreal.MaterialExpressionTextureSample)
                expression.set_editor_property('texture',texture)
                expression.set_editor_property('sampler_type',sampler)
                if not library.connect_material_property(expression,'RGB' if channel in ('basecolor','normal') else 'R',properties[channel]):
                    raise RuntimeError('Failed material connection: '+channel)
        library.layout_material_expressions(material)
        library.recompile_material(material)
        if not unreal.EditorAssetLibrary.save_loaded_asset(material):
            raise RuntimeError('Failed saving material: '+asset_id)
        report['assets'].append({'id':asset_id,'material':material.get_path_name(),'textures':imported,
                                 'unbound_source_maps':{k:v['path'] for k,v in asset['maps'].items() if k not in properties},
                                 'source':asset['source'],'license':asset['license']})
    Path(config['report']).write_text(json.dumps(report,indent=2)+'\n')
    unreal.log('L3_MATERIAL_IMPORT_COMPLETE '+str(len(report['assets'])))

if __name__=='__main__':
    main()

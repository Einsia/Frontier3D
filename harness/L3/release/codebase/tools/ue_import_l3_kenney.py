"""UE commandlet: import the fixed CC0 voxel texture library, without any scene."""
import hashlib
import json
import os
from pathlib import Path
import unreal

root=Path(os.environ.get('L3_KENNEY_ROOT','/assets/kenney'))
manifest=json.loads((root/'manifest.json').read_text())
assert manifest['status']=='complete'
tools=unreal.AssetToolsHelpers.get_asset_tools()
library=unreal.MaterialEditingLibrary
report={'provider':'Kenney','license':manifest['license'],'source':manifest['source'],
        'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),'assets':[]}
for entry in manifest['files']:
    if not entry['path'].endswith('.png'):continue
    source=root/entry['path'];assert hashlib.sha256(source.read_bytes()).hexdigest()==entry['sha256']
    name=source.stem;destination='/Game/L3Materials/Kenney'
    texture=unreal.load_asset(destination+'/T_'+name) if unreal.EditorAssetLibrary.does_asset_exist(destination+'/T_'+name) else None
    if texture is None:
        task=unreal.AssetImportTask();task.filename=str(source);task.destination_path=destination
        task.destination_name='T_'+name;task.automated=True;task.replace_existing=False;task.save=False
        tools.import_asset_tasks([task]);assert len(task.imported_object_paths)==1
        texture=unreal.load_asset(task.imported_object_paths[0])
    texture.set_editor_property('srgb',True)
    texture.set_editor_property('filter',unreal.TextureFilter.TF_NEAREST)
    texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_DEFAULT)
    assert unreal.EditorAssetLibrary.save_loaded_asset(texture)
    material=unreal.load_asset(destination+'/M_'+name) if unreal.EditorAssetLibrary.does_asset_exist(destination+'/M_'+name) else tools.create_asset('M_'+name,destination,unreal.Material,unreal.MaterialFactoryNew())
    assert material
    library.delete_all_material_expressions(material)
    material.set_editor_property('used_with_instanced_static_meshes',True)
    expression=library.create_material_expression(material,unreal.MaterialExpressionTextureSample)
    expression.set_editor_property('texture',texture)
    expression.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    uv=library.create_material_expression(material,unreal.MaterialExpressionTextureCoordinate)
    scale=library.create_material_expression(material,unreal.MaterialExpressionScalarParameter)
    scale.set_editor_property('parameter_name','UVScale')
    scale.set_editor_property('default_value',1.0)
    multiply=library.create_material_expression(material,unreal.MaterialExpressionMultiply)
    assert library.connect_material_expressions(uv,'',multiply,'A')
    assert library.connect_material_expressions(scale,'',multiply,'B')
    assert library.connect_material_expressions(multiply,'',expression,'UVs')
    assert library.connect_material_property(expression,'RGB' ,unreal.MaterialProperty.MP_BASE_COLOR)
    if name in {'grass1','grass2','grass3','grass4','leaves_transparent','leaves_orange_transparent','glass'} or name.startswith('wheat_stage'):
        material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_MASKED)
        material.set_editor_property('two_sided',True)
        assert library.connect_material_property(expression,'A',unreal.MaterialProperty.MP_OPACITY_MASK)
    rough=library.create_material_expression(material,unreal.MaterialExpressionConstant)
    rough.set_editor_property('r',0.85)
    library.connect_material_property(rough,'',unreal.MaterialProperty.MP_ROUGHNESS)
    library.recompile_material(material)
    assert unreal.EditorAssetLibrary.save_loaded_asset(material)
    report['assets'].append({'id':name,'source_sha256':entry['sha256'],'texture':texture.get_path_name(),'material':material.get_path_name()})
# A generic two-sided unlit sky for the equipment fixture. No scene geometry.
sky_path='/Game/L3Environment/M_DefaultSky'
sky=unreal.load_asset(sky_path) if unreal.EditorAssetLibrary.does_asset_exist(sky_path) else tools.create_asset('M_DefaultSky','/Game/L3Environment',unreal.Material,unreal.MaterialFactoryNew())
library.delete_all_material_expressions(sky)
sky.set_editor_property('two_sided',True)
sky.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
color=library.create_material_expression(sky,unreal.MaterialExpressionConstant3Vector)
color.set_editor_property('constant',unreal.LinearColor(0.20,0.42,0.70,1.0))
library.connect_material_property(color,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
library.recompile_material(sky)
assert unreal.EditorAssetLibrary.save_loaded_asset(sky)
Path(os.environ.get('L3_IMPORT_REPORT','/workspace/kenney-import.json')).write_text(json.dumps(report,indent=2)+'\n')
unreal.log('L3_KENNEY_IMPORT_COMPLETE '+str(len(report['assets'])))

"""Evaluator-only UE commandlet; creates a known unlit instance-mask material."""
import unreal
tools=unreal.AssetToolsHelpers.get_asset_tools()
path='/Game/L3Verifier/M_InstanceMask'
if unreal.EditorAssetLibrary.does_asset_exist(path):
    assert unreal.EditorAssetLibrary.delete_asset(path)
material=tools.create_asset('M_InstanceMask','/Game/L3Verifier',unreal.Material,unreal.MaterialFactoryNew())
material.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
material.set_editor_property('used_with_instanced_static_meshes',True)
expression=unreal.MaterialEditingLibrary.create_material_expression(material,unreal.MaterialExpressionVectorParameter)
expression.set_editor_property('parameter_name','IdColor')
assert unreal.MaterialEditingLibrary.connect_material_property(expression,'RGB',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
unreal.MaterialEditingLibrary.recompile_material(material)
assert unreal.EditorAssetLibrary.save_loaded_asset(material)
unreal.log('L3_TRUSTED_MASK_MATERIAL_READY')

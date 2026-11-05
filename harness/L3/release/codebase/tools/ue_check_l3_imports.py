"""Organizer-only imported asset inspection and render fixture, not a task solution."""
import json,os
from pathlib import Path
import unreal

def main():
 cfg=json.loads(Path(os.environ['L3_ASSET_CHECK']).read_text());models=json.loads(Path(cfg['models']).read_text())['models'];pbr=json.loads(Path(cfg['materials']).read_text())['assets'];rows=[]
 assert unreal.EditorLevelLibrary.new_level('/Game/L3AssetImportSmoke')
 for i,row in enumerate(models):
  mesh=unreal.load_asset(row['object_path']);bounds=mesh.get_bounds();extent=bounds.box_extent;scale=150/(2*extent.z)
  if min(extent.x,extent.y,extent.z)<=0:raise ValueError('Degenerate mesh')
  actor=unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor,unreal.Vector(2000+i*300,0,0));component=actor.static_mesh_component;component.set_static_mesh(mesh);actor.set_actor_scale3d(unreal.Vector(scale,scale,scale));actor.set_actor_location(unreal.Vector(2000+i*300,0,(extent.z-bounds.origin.z)*scale),False,False)
  materials=[]
  for slot in mesh.static_materials:
   mat=slot.material_interface
   if mat is None:raise ValueError('Missing imported material '+row['source'])
   materials.append(mat.get_path_name())
  if not materials:raise ValueError('No material slots '+row['source'])
  rows.append({**row,'materials':materials,'display_scale':scale,'display_height_cm':150})
 floor=unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor,unreal.Vector(2900,100,-20));floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Cube.Cube'));floor.set_actor_scale3d(unreal.Vector(28,14,.4))
 for i,mat in enumerate(pbr):
  obj=unreal.load_asset(mat['material']);assert obj
  for tex in mat['textures'].values():assert isinstance(unreal.load_asset(tex['object_path']),unreal.Texture2D)
  cube=unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.StaticMeshActor,unreal.Vector(2600+i*300,400,75));cube.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Cube.Cube'));cube.set_actor_scale3d(unreal.Vector(1.5,1.5,1.5));cube.static_mesh_component.set_material(0,obj)
 assert unreal.EditorLevelLibrary.save_current_level()
 Path(cfg['report']).write_text(json.dumps({'passed':True,'models':rows,'pbr_materials':pbr,'map':'/Game/L3AssetImportSmoke','scope':'Organizer asset import fixture; models normalized to 150 cm height only for display, not task geometry.'},indent=2)+'\n')
if __name__=='__main__':main()

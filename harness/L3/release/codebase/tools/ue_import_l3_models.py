"""UE commandlet importer for selected offline Kenney FBX models."""
import hashlib,json,os,re
from pathlib import Path
import unreal

def main():
 cfg=json.loads(Path(os.environ['L3_MODEL_IMPORT']).read_text());root=Path(cfg['library']).resolve();manifest=json.loads((root/'manifest.json').read_text())
 catalog={f['path']:f for p in manifest['packs'] for f in p['files']};tools=unreal.AssetToolsHelpers.get_asset_tools();rows=[]
 for rel in cfg['paths']:
  p=(root/rel).resolve()
  if not p.is_relative_to(root) or rel not in catalog or p.suffix.lower()!='.fbx':raise ValueError('Model must be a catalogued FBX')
  if hashlib.sha256(p.read_bytes()).hexdigest()!=catalog[rel]['sha256']:raise ValueError('Model hash mismatch')
  pack=rel.split('/')[0];name=re.sub('[^A-Za-z0-9_]','_',p.stem);dest='/Game/L3Props/'+pack.replace('-','_')+'/'+name;asset=dest+'/SM_'+name
  if not unreal.EditorAssetLibrary.does_asset_exist(asset):
   task=unreal.AssetImportTask();task.filename=str(p);task.destination_path=dest;task.destination_name='SM_'+name;task.automated=True;task.save=True;task.replace_existing=False
   opts=unreal.FbxImportUI();opts.import_mesh=True;opts.import_as_skeletal=False;opts.import_materials=True;opts.import_textures=True;opts.import_animations=False
   opts.mesh_type_to_import=unreal.FBXImportType.FBXIT_STATIC_MESH
   opts.static_mesh_import_data.combine_meshes=True;opts.static_mesh_import_data.auto_generate_collision=True;opts.static_mesh_import_data.convert_scene=True;opts.static_mesh_import_data.convert_scene_unit=True
   task.options=opts;tools.import_asset_tasks([task])
   meshes=[x for x in task.imported_object_paths if isinstance(unreal.load_asset(x),unreal.StaticMesh)]
   if len(meshes)!=1:raise RuntimeError('Expected one combined mesh: '+rel+' '+str(list(task.imported_object_paths)))
   asset=meshes[0]
  obj=unreal.load_asset(asset)
  if not isinstance(obj,unreal.StaticMesh):raise RuntimeError('Not a static mesh '+asset)
  bounds=obj.get_bounds();rows.append({'source':rel,'sha256':catalog[rel]['sha256'],'object_path':obj.get_path_name(),'bounds_extent_cm':[bounds.box_extent.x,bounds.box_extent.y,bounds.box_extent.z],'license':'CC0-1.0'})
 Path(cfg['report']).write_text(json.dumps({'models':rows,'engine':unreal.SystemLibrary.get_engine_version()},indent=2)+'\n')
 unreal.log('L3_MODEL_IMPORT_COMPLETE '+str(len(rows)))
if __name__=='__main__':main()

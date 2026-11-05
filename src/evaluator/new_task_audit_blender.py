"""Read-only inspection and authored-camera rerenders for newly added tasks."""
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    import bpy
    from mathutils import Vector
    sys.path.insert(0,str(Path(__file__).parent))
    from continuous_native_blender import inspect
    request_path=Path(sys.argv[sys.argv.index('--')+1]);request=json.loads(request_path.read_text())
    out=Path(request['output']);out.mkdir(parents=True,exist_ok=True)
    source=Path(request['scene']['path'])
    if digest(source)!=request['scene']['sha256']:raise ValueError('Input scene changed')
    if request.get('inspect_only'):
        result=inspect({'scene':request['scene'],'frames':[1]},out)
        (out/'result.json').write_text(json.dumps({'result':result,'request_sha256':digest(request_path),'worker_sha256':digest(__file__)},ensure_ascii=False,allow_nan=False,indent=2)+'\n')
        return
    bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
    scene=bpy.context.scene;scene.frame_set(1);bpy.context.view_layer.update()
    cameras=[o.name for o in scene.objects if o.type=='CAMERA']
    if not cameras:raise ValueError('No retained camera for native rerender')
    active=scene.camera.name if scene.camera else cameras[0]
    cameras=[active]+[n for n in sorted(cameras) if n!=active]
    cameras=cameras[:8]
    saved_settings={'engine':scene.render.engine,'resolution':[scene.render.resolution_x,scene.render.resolution_y],
        'percentage':scene.render.resolution_percentage,'view_transform':scene.view_settings.view_transform,
        'exposure':scene.view_settings.exposure,'gamma':scene.view_settings.gamma,
        'cycles_samples':scene.cycles.samples,'camera':active}
    result={'scene':request['scene'],'saved_settings':saved_settings,'retained_cameras':cameras,'renders':{},
        'comparison_policy':'All retained cameras, original transforms/lenses/materials/lights. Re-render resolution capped at 640; Cycles sampling capped at 32 for diagnostic comparisons. No geometry fitting.',
        'autoexec':False,'source_unchanged':None}
    original_x,original_y=scene.render.resolution_x,scene.render.resolution_y
    proportion=min(1,640/max(original_x,original_y))
    scene.render.resolution_x=max(1,round(original_x*proportion));scene.render.resolution_y=max(1,round(original_y*proportion));scene.render.resolution_percentage=100
    scene.render.threads_mode='FIXED';scene.render.threads=4
    if scene.render.engine=='CYCLES':
        scene.cycles.device='CPU';scene.cycles.samples=min(scene.cycles.samples,32)
    scene.render.image_settings.file_format='PNG'
    for i,name in enumerate(cameras):
        scene.camera=bpy.data.objects[name]
        path=out/f'camera-{i}.png';scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
        result['renders'][name]={'path':str(path),'sha256':digest(path),'camera_matrix_world':[list(v) for v in scene.camera.matrix_world]}
    if request['level']==1:
        camera=bpy.data.objects[active].copy();camera.data=camera.data.copy();scene.collection.objects.link(camera)
        camera.location+=camera.matrix_world.to_quaternion()@Vector((.30/scene.unit_settings.scale_length,0,0))
        scene.camera=camera;path=out/'alternate.png';scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
        result['alternate']={'path':str(path),'sha256':digest(path),'camera_policy':'authored active camera translated +0.30 metres along local X; unchanged rotation/lens; diagnostic only'}
    result['source_unchanged']=digest(source)==request['scene']['sha256']
    if not result['source_unchanged']:raise ValueError('Native source changed')
    (out/'result.json').write_text(json.dumps({'result':result,'request_sha256':digest(request_path),'worker_sha256':digest(__file__)},ensure_ascii=False,allow_nan=False,indent=2)+'\n')

if __name__=='__main__':main()

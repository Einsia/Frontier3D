"""Opaque complete-scene silhouettes from historically bound saved L2 cameras."""
import hashlib
import json
from pathlib import Path
import sys

CAMERA_FIELDS=('type','lens','sensor_fit','sensor_width','sensor_height','ortho_scale',
               'shift_x','shift_y','clip_start','clip_end')


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    import bpy
    sys.path.insert(0,str(Path(__file__).parent))
    from l1_image_blender import geometry_mask
    path=Path(sys.argv[sys.argv.index('--')+1]);request=json.loads(path.read_text())
    root=Path(__file__).resolve().parents[2]
    for name,expected in request['implementation'].items():
        if sha(root/name)!=expected:raise ValueError('Silhouette implementation changed')
    source=request['scene'];scene_path=Path(source['path'])
    if sha(scene_path)!=source['sha256']:raise ValueError('Retained scene changed')
    bpy.ops.wm.open_mainfile(filepath=str(scene_path),load_ui=False,use_scripts=False)
    scene=bpy.context.scene;scene.frame_set(request['frame'])
    obj=scene.objects.get(request['camera']['object'])
    if obj is None or obj.type!='CAMERA':raise ValueError('Historically verified render camera is absent')
    record={'object':obj.name,'matrix_world':[list(v) for v in obj.matrix_world],
        'unit_scale':scene.unit_settings.scale_length,
        'settings':{k:getattr(obj.data,k) for k in CAMERA_FIELDS}}
    if record!=request['camera']:raise ValueError('Saved camera projection differs from complete property extraction')
    if obj.data.type not in ('PERSP','ORTHO'):raise ValueError('Unsupported camera projection')
    size=[scene.render.resolution_x*scene.render.resolution_percentage//100,
          scene.render.resolution_y*scene.render.resolution_percentage//100]
    if size!=request['resolution']:raise ValueError('Reference and saved render pixel grids differ; no rescaling')
    if scene.render.use_border or scene.render.use_crop_to_border or scene.render.use_multiview:
        raise ValueError('An uncropped single pixel grid is required')
    if sum(layer.use for layer in scene.view_layers)!=1:raise ValueError('Single verified render layer required')
    if scene.render.pixel_aspect_x!=scene.render.pixel_aspect_y:raise ValueError('Non-square saved pixels require explicit calibration')
    scene.camera=obj
    output=Path(request['mask']);output.parent.mkdir(parents=True,exist_ok=True)
    geometry_mask(scene,output)
    if sha(scene_path)!=source['sha256']:raise ValueError('Worker modified retained scene')
    result={'scene':source,'source_unchanged':True,'camera':record,'frame':scene.frame_current,
        'resolution':size,'mask':{'path':str(output),'sha256':sha(output)},
        'mask_protocol':'opaque-evaluated-geometry-alpha-v1','scope':'all_visible_opaque_geometry',
        'candidate_code_executed':False,'autoexec':False,'request_sha256':sha(path),
        'implementation':request['implementation']}
    Path(request['output']).write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()

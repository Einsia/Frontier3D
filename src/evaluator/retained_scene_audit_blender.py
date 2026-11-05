"""Small independent read-only census; no BMesh analysis or scene mutation."""
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    import bpy
    request_path=Path(sys.argv[sys.argv.index('--')+1]);request=json.loads(request_path.read_text())
    source=request['scene'];assert sha(source['path'])==source['sha256']
    bpy.ops.wm.open_mainfile(filepath=source['path'],load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    users=bpy.data.user_map();used={scene}
    while True:
        expanded=used | {block for block,owners in users.items() if owners & used}
        if expanded==used:break
        used=expanded
    dependencies=[];ignored=[]
    for lib in bpy.data.libraries:
        consumers=[b.name for b in used if getattr(b,'library',None)==lib]
        (dependencies if consumers else ignored).append({'path':lib.filepath,'scene_users':consumers})
    images=[]
    for im in bpy.data.images:
        if im not in used:continue
        packed=[hashlib.sha256(bytes(p.data)).hexdigest() for p in ([im.packed_file] if im.packed_file else [])]
        images.append({'name':im.name,'packed_sha256':packed,'source':im.source,'path':im.filepath})
    visible=[];invalid=[]
    for obj in scene.objects:
        if obj.type!='MESH' or obj.hide_render:continue
        mesh=obj.data;visible.append({'name':obj.name,'vertices':len(mesh.vertices),'polygons':len(mesh.polygons)})
        if any(loop.vertex_index<0 or loop.vertex_index>=len(mesh.vertices) for loop in mesh.loops):invalid.append(obj.name)
    result={'protocol':'retained-scene-census-v1','scene':source,'worker_sha256':sha(__file__),
        'request_sha256':sha(request_path),'source_unchanged':sha(source['path'])==source['sha256'],
        'candidate_code_executed':False,'visible_meshes':visible,'invalid_meshes':invalid,
        'scene_reachable_libraries':dependencies,'unused_libraries':ignored,'used_images':images,
        'active_camera':scene.camera.name if scene.camera else None,'saved_frame':scene.frame_current,
        'render_size':[round(scene.render.resolution_x*scene.render.resolution_percentage/100),
                       round(scene.render.resolution_y*scene.render.resolution_percentage/100)],
        'cameras':sorted(o.name for o in scene.objects if o.type=='CAMERA')}
    Path(request['output']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()

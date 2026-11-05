"""Trace exact reference-image uses into active material/world output paths."""
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    import bpy
    request_path=Path(sys.argv[sys.argv.index('--')+1]);req=json.loads(request_path.read_text())
    source=req['scene'];assert sha(source['path'])==source['sha256']
    bpy.ops.wm.open_mainfile(filepath=source['path'],load_ui=False,use_scripts=False)
    refs=set(req['reference_sha256']);uses=[];scene=bpy.context.scene
    def reaches(node,seen):
        if node.as_pointer() in seen:return False
        seen=seen|{node.as_pointer()}
        if node.bl_idname in {'ShaderNodeOutputMaterial','ShaderNodeOutputWorld'}:return bool(getattr(node,'is_active_output',True))
        return any(reaches(link.to_node,seen) for socket in node.outputs for link in socket.links)
    for obj in scene.objects:
        if obj.hide_render:continue
        for slot in obj.material_slots:
            mat=slot.material
            if not mat or not mat.node_tree:continue
            for node in mat.node_tree.nodes:
                im=getattr(node,'image',None)
                if im and im.packed_file:
                    digest=hashlib.sha256(bytes(im.packed_file.data)).hexdigest()
                    if digest in refs:uses.append(dict(object=obj.name,material=mat.name,node=node.name,image=im.name,
                        sha256=digest,linked_to_active_output=reaches(node,set()),muted=node.mute,
                        object_type=obj.type,vertices=len(obj.data.vertices) if obj.type=='MESH' else None,
                        polygons=len(obj.data.polygons) if obj.type=='MESH' else None))
    result=dict(protocol='reference-texture-trace-v1',scene=source,reference_sha256=sorted(refs),uses=uses,
        source_unchanged=sha(source['path'])==source['sha256'],worker_sha256=sha(__file__),request_sha256=sha(request_path),
        candidate_code_executed=False,scope='Direct image nodes in visible-object material trees; nested groups require separate review')
    Path(req['output']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()

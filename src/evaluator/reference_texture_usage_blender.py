"""Read-only reference use and exact, direct UV support; never execute candidates."""
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    import bpy
    request=Path(sys.argv[sys.argv.index('--')+1]);req=json.loads(request.read_text())
    source=req['scene'];assert sha(source['path'])==source['sha256']
    bpy.ops.wm.open_mainfile(filepath=source['path'],load_ui=False,use_scripts=False)
    scene=bpy.context.scene;refs=set(req['reference_sha256']);uses=[]
    users=bpy.data.user_map();used={scene}
    while True:
        expanded=used | {block for block,owners in users.items() if owners & used}
        if expanded==used:break
        used=expanded
    def digest(im):
        return hashlib.sha256(bytes(im.packed_file.data)).hexdigest() if im and im.packed_file else None
    reachable=[im.name for im in bpy.data.images if im in used and digest(im) in refs]
    def reaches(node,seen):
        if node.as_pointer() in seen:return False
        seen=seen|{node.as_pointer()}
        if node.bl_idname in {'ShaderNodeOutputMaterial','ShaderNodeOutputWorld'}:return bool(getattr(node,'is_active_output',True))
        return any(reaches(l.to_node,seen) for socket in node.outputs for l in socket.links)
    for obj in scene.objects:
        if obj.hide_render:continue
        for slot_index,slot in enumerate(obj.material_slots):
            mat=slot.material
            if not mat or not mat.node_tree:continue
            for node in mat.node_tree.nodes:
                im=getattr(node,'image',None);h=digest(im)
                if h not in refs:continue
                row=dict(object=obj.name,material=mat.name,node=node.name,image=im.name,sha256=h,
                    linked_to_active_output=reaches(node,set()),muted=node.mute,uv_supported=False,
                    object_type=obj.type,vertices=len(obj.data.vertices) if obj.type=='MESH' else None,
                    polygons=len(obj.data.polygons) if obj.type=='MESH' else None)
                if obj.type=='MESH' and node.bl_idname=='ShaderNodeTexImage' and node.projection=='FLAT':
                    vector=node.inputs['Vector'];uv=obj.data.uv_layers.active
                    if not vector.is_linked:row['uv_supported']=True
                    elif len(vector.links)==1 and vector.links[0].from_node.bl_idname=='ShaderNodeUVMap':
                        uv=obj.data.uv_layers.get(vector.links[0].from_node.uv_map) or uv;row['uv_supported']=True
                    if uv and row['uv_supported']:
                        indices=[li for poly in obj.data.polygons if poly.material_index==slot_index for li in poly.loop_indices]
                        coords=[uv.data[li].uv for li in indices]
                        if coords:
                            low=[min(c[a] for c in coords) for a in (0,1)];high=[max(c[a] for c in coords) for a in (0,1)]
                            row.update(uv_min=low,uv_max=high,uv_area=(high[0]-low[0])*(high[1]-low[1]),uv_samples=len(coords))
                uses.append(row)
    # Any reachable reference not accounted for by direct visible material nodes
    # stays unresolved (world, compositor, groups, hidden objects, modifiers...).
    accounted={r['image'] for r in uses}
    result=dict(protocol='reference-texture-usage-v2',scene=source,reference_sha256=sorted(refs),uses=uses,
        reachable_reference_images=reachable,unaccounted_reference_images=sorted(set(reachable)-accounted),
        source_unchanged=sha(source['path'])==source['sha256'],worker_sha256=sha(__file__),request_sha256=sha(request),
        candidate_code_executed=False)
    Path(req['output']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()

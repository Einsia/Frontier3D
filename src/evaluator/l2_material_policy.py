"""Blender-side image-texture inventory for the procedural-material protocol.

Inspect scene-owned shader/node dependencies; packed/generated images are images
too. This is deliberately stricter than the old missing-resource check.
"""
from __future__ import annotations


def procedural_material_inventory(scene):
    import bpy
    violations=[];visited=set();trees=[];materials=set();objects=[]

    def record(kind, owner, name):
        violations.append({'kind':kind,'owner':owner,'name':name})

    def dependency(value,owner,depth=0):
        if value is None or depth>8:return
        if isinstance(value,bpy.types.Image):
            record('image_datablock',owner,value.name)
        elif isinstance(value,bpy.types.Texture):
            if value.type=='IMAGE':record('legacy_image_texture',owner,value.name)
            if getattr(value,'node_tree',None):visit(value.node_tree,owner)
        elif isinstance(value,bpy.types.Material):material(value)
        elif isinstance(value,bpy.types.NodeTree):visit(value,owner)

    def visit(tree,owner):
        if tree is None:return
        key=tree.as_pointer()
        if key in visited:return
        visited.add(key);trees.append({'name':tree.name,'owner':owner})
        for node in tree.nodes:
            node_owner=owner+'/'+node.name
            # Inspect all nodes in a live tree, including muted/unlinked nodes;
            # the public protocol forbids retaining image texture nodes there.
            kind=node.bl_idname
            if kind in {'ShaderNodeTexImage','ShaderNodeTexEnvironment','GeometryNodeImageTexture',
                        'GeometryNodeInputImage','CompositorNodeImage','CompositorNodeMovieClip',
                        'CompositorNodeTexture'}:
                record('image_node',node_owner,kind)
            for prop in node.bl_rna.properties:
                if prop.type=='POINTER' and prop.identifier!='rna_type':
                    dependency(getattr(node,prop.identifier,None),node_owner)
            for socket in node.inputs:
                dependency(getattr(socket,'default_value',None),node_owner+'/'+socket.identifier)

    def material(value):
        if value.as_pointer() in materials:return
        materials.add(value.as_pointer())
        visit(value.node_tree,'material:'+value.name)

    for obj in scene.objects:
        objects.append(obj.name)
        for slot in obj.material_slots:
            if slot.material:material(slot.material)
        data=obj.data
        if getattr(data,'node_tree',None):visit(data.node_tree,obj.type+':'+obj.name)
        for modifier in obj.modifiers:
            owner='modifier:'+obj.name+'/'+modifier.name
            for prop in modifier.bl_rna.properties:
                if prop.type=='POINTER' and prop.identifier!='rna_type':
                    dependency(getattr(modifier,prop.identifier,None),owner)
            try:values=modifier.values()
            except TypeError:values=[]
            for value in values:dependency(value,owner)
    if scene.world:visit(scene.world.node_tree,'world:'+scene.world.name)
    compositor=getattr(scene,'compositing_node_group',None) or getattr(scene,'node_tree',None)
    visit(compositor,'compositor')
    unique={tuple(sorted(v.items())):v for v in violations}
    violations=sorted(unique.values(),key=lambda v:(v['owner'],v['kind'],v['name']))
    return {'protocol':'l2-procedural-materials-v1','passed':not violations,
        'violation_count':len(violations),'violations':violations,'inspected_trees':trees,
        'material_count':len(materials),'object_count':len(objects),
        'scope':'Scene shader/world/light/compositor trees, nested groups and modifier image dependencies; image nodes in live trees are forbidden even if packed, generated, muted or unlinked.',
        'allowed':'Solid colors and procedural shader/math/noise nodes without image sources.'}

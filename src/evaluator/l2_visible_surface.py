"""Blender ray samples of visible native geometry, independent of beauty images."""
import math


def visible_surface(scene,width=160):
    import bpy
    from mathutils import Vector
    camera=scene.camera
    if camera is None or camera.data.type not in {'PERSP','ORTHO'}:
        return {'status':'not_measurable','reason':'Perspective/orthographic primary camera required'}
    height=max(1,round(width*scene.render.resolution_y*scene.render.pixel_aspect_y/
                       (scene.render.resolution_x*scene.render.pixel_aspect_x)))
    frame=camera.data.view_frame(scene=scene)
    low=[min(p[i] for p in frame) for i in (0,1)];high=[max(p[i] for p in frame) for i in (0,1)]
    z=frame[0].z;matrix=camera.matrix_world;depsgraph=bpy.context.evaluated_depsgraph_get()
    depths=[];points=[];owners=[];normals=[];hidden_hits=0
    scale=scene.unit_settings.scale_length
    for iy in range(height):
        for ix in range(width):
            x=low[0]+(high[0]-low[0])*(ix+.5)/width
            y=high[1]-(high[1]-low[1])*(iy+.5)/height
            origin=matrix.translation if camera.data.type=='PERSP' else matrix@Vector((x,y,0))
            direction=(matrix@Vector((x,y,z))-origin).normalized()
            hit,location,normal,index,obj,_=scene.ray_cast(depsgraph,origin,direction)
            valid=hit and not obj.hide_render and any(not c.hide_render for c in obj.users_collection)
            if hit and not valid:hidden_hits+=1
            if valid:
                distance=float((location-origin).length*scale)
                if not math.isfinite(distance):raise ValueError('Non-finite visible surface depth')
                depths.append(distance);points.append([float(v*scale) for v in location])
                normals.append(list(normal));owners.append(obj.original.name)
            else:
                depths.append(None);points.append(None);normals.append(None);owners.append(None)
    return {'status':'not_measurable' if hidden_hits else 'measured','hidden_hit_count':hidden_hits,
            'reason':'Render-hidden occluders need a render-visibility-aware ray query' if hidden_hits else None,
            'size':[width,height],'camera':camera.name,'depth_m':depths,
            'world_points_m':points,'normals':normals,'object_names':owners,
            'scope':'First geometry intersection in the saved main camera. Transparency/refraction are not modeled; sampled, not a full semantic/thickness certificate.'}

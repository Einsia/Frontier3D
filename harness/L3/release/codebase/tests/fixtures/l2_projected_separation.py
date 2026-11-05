"""Projection-only controls keep existing craters and complete site geometry."""
if NUMBER==2:
    cx,cy=6.,4.;r=1.25
    # The auxiliary apron pieces deliberately use a lower elevation so the
    # existing depression visibility test does not cause a coincidental rejection.
    # This fixture verifies XY exclusion, not a complete semantic apron design.
    z=-.6
    if MODE in {'crater_apron_overlap','crater_apron_sliver','apron_boundary_contact'}:
        overlap={'crater_apron_overlap':.1,'crater_apron_sliver':.00002,'apron_boundary_contact':0.}[MODE]
        right=cx-r+overlap
        box('apron',(right-.25,cy,z),(.5,2*r,.03))
    if MODE in {'crater_in_apron_hole','crater_in_filled_apron_hole'}:
        inside=1.3;outside=1.8
        for side in (-1,1):
            box('apron',(cx+side*(inside+outside)/2,cy,z),(outside-inside,2*outside,.03))
            box('apron',(cx,cy+side*(inside+outside)/2,z),(2*inside,outside-inside,.03))
        if MODE=='crater_in_filled_apron_hole':box('apron',(cx,cy,z),(2*inside,2*inside,.03))
    if MODE=='buried_apron_overlap':box('apron',(cx,cy,-10),(2*r,2*r,.03))
    if MODE=='split_crater_mesh':
        original=roles['crater'][0];root=parent('crater');points=[original.matrix_world@v.co for v in original.data.vertices]
        # Four row bands preserve every face exactly and share one entity.
        faces=list(original.data.polygons);chunks=[[],[],[],[]]
        for face in faces:chunks[min(3,face.index//144)].append(tuple(face.vertices))
        for chunk in chunks:
            mesh=bpy.data.meshes.new('split_actual_crater');mesh.from_pydata(points,[],chunk);mesh.update()
            obj=bpy.data.objects.new('split_actual_crater',mesh);scene.collection.objects.link(obj);register(obj,'crater',root)
        roles['crater'].remove(original);bpy.data.objects.remove(original,do_unlink=True)
    if MODE=='rotated_exclusion_geometry':
        from mathutils import Matrix
        bpy.context.view_layer.update()
        rotation=Matrix.Rotation(math.radians(31),4,'Z')
        for obj in list(scene.objects):
            if obj.parent is None:obj.matrix_world=rotation@obj.matrix_world

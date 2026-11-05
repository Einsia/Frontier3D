"""Closed-cavity and embedded-material controls, independent of object splits."""
if NUMBER == 2 and MODE in {'sealed_support_cavity','split_cavity_shells','embedded_material_piece',
        'nested_filled_solids','reversed_hollow_support','floating_cavity_piece','open_support_shell',
        'open_inner_boundary','misoriented_inner_face'}:
    def rewrite_faces(obj, operation):
        vertices=[tuple(v.co) for v in obj.data.vertices]
        faces=[list(p.vertices) for p in obj.data.polygons]
        if operation=='reverse':faces=[face[::-1] for face in faces]
        elif operation=='open':faces=faces[1:]
        elif operation=='one_reverse':faces[0]=faces[0][::-1]
        mesh=bpy.data.meshes.new('closed_boundary_control')
        mesh.from_pydata(vertices,[],faces);mesh.update()
        for material in obj.data.materials:mesh.materials.append(material)
        obj.data=mesh

    outer=roles['rail_support'][0];x,y=float(outer.location.x),float(outer.location.y)
    root=parent('rail_support');outer.parent=root
    inner=box('rail_support',(x,y,1.325),(.15,.15,2.55),root)
    if MODE!='nested_filled_solids':rewrite_faces(inner,'reverse')
    if MODE in {'floating_cavity_piece','nested_filled_solids'}:
        box('rail_support',(x,y,1.3),(.05,.05,.2),root)
    if MODE=='embedded_material_piece':
        box('rail_support',(x+.1,y,1.3),(.004,.05,.2),root)
    if MODE=='open_support_shell':rewrite_faces(outer,'open')
    if MODE=='open_inner_boundary':rewrite_faces(inner,'open')
    if MODE=='misoriented_inner_face':rewrite_faces(inner,'one_reverse')
    if MODE=='reversed_hollow_support':
        for obj in (outer,inner):rewrite_faces(obj,'reverse')
    if MODE=='split_cavity_shells':
        bpy.context.view_layer.update()
        for obj in (outer,inner):
            vertices=[tuple(obj.matrix_world@v.co) for v in obj.data.vertices]
            faces=[list(p.vertices) for p in obj.data.polygons]
            for face in faces:
                mesh=bpy.data.meshes.new('split_boundary_face')
                mesh.from_pydata([vertices[i] for i in face],[],[list(range(len(face)))]);mesh.update()
                piece=bpy.data.objects.new('separate_face',mesh);scene.collection.objects.link(piece)
                register(piece,'rail_support',root)
            bpy.data.objects.remove(obj,do_unlink=True)

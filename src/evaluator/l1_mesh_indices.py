"""Check native mesh references before handing them to Blender's C kernels."""


def invalid_reference(mesh):
    vertices, edges, loops = len(mesh.vertices), len(mesh.edges), len(mesh.loops)
    for edge in mesh.edges:
        for index in edge.vertices:
            if not 0 <= index < vertices:
                return dict(kind='edge_vertex', element=edge.index, index=index,
                            vertex_count=vertices)
    for loop in mesh.loops:
        if not 0 <= loop.vertex_index < vertices:
            return dict(kind='loop_vertex', element=loop.index, index=loop.vertex_index,
                        vertex_count=vertices)
        if not 0 <= loop.edge_index < edges:
            return dict(kind='loop_edge', element=loop.index, index=loop.edge_index,
                        edge_count=edges)
    for polygon in mesh.polygons:
        if polygon.loop_start < 0 or polygon.loop_total < 3 or polygon.loop_start + polygon.loop_total > loops:
            return dict(kind='polygon_loops', element=polygon.index,
                        start=polygon.loop_start, count=polygon.loop_total, loop_count=loops)
    return None

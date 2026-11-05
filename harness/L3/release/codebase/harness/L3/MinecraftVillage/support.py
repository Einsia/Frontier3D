"""L2 complete-surface support with per-actor counts, not a terrain-area headline."""
from collections import Counter
from .pilot_geometry import world_geometry
from .contact import contact


def measure(exported, *, maximum_triangles=1_000_000, maximum_pieces=100000, maximum_triangle_pairs=20_000_000, reviewed_ground=None):
    import src.evaluator.l2_physical as l2
    from src.evaluator.l2_support_chain import pieces
    visible=dict(exported,instances=[i for i in exported['instances'] if i.get('visible',True)])
    groups=world_geometry(visible)
    evidence={'scene':{'objects':{name:{'type':'MESH','visible_render':True,'surface_triangles':v} for name,v in groups.items()}}}
    if reviewed_ground is not None:evidence['reviewed_ground']=reviewed_ground
    original=l2.contact
    original_pieces=l2.pieces
    def complete_pieces(surface, **kwargs):
        return pieces(surface,maximum_triangles=maximum_triangles,**kwargs)
    try:
        l2.contact=contact
        l2.pieces=complete_pieces
        measured=l2.physical_plausibility(evidence,dict(l2.DEFAULT_POLICY),maximum_pieces=maximum_pieces,maximum_triangle_pairs=maximum_triangle_pairs)
    finally:
        l2.contact=original
        l2.pieces=original_pieces
    failures=Counter(row['object'] for row in measured.get('unsupported',[]))
    rows=[]
    for name,surface in groups.items():
        total=len(complete_pieces(surface,maximum_pieces=maximum_pieces))
        bad=failures[name]
        rows.append({'actor':name,'connected_piece_count':total,'unsupported_piece_count':bad,
                     'all_pieces_connected_to_ground':bad==0 if measured.get('status')=='measured' else None})
    return {'method':'l2_support_with_actor_coverage_v1','actors':rows,
            'actors_with_disconnected_pieces':sum(v>0 for v in failures.values()),
            'actor_count':len(rows),'unsupported_piece_count':measured.get('unsupported_piece_count'),
            'raw_l2':measured,'formal_layout_score':None,
            'scope':'Per-actor diagnostics prevent terrain surface area from hiding unsupported parts. Actor names are grouping hints; support/attachment semantics and load stability still require task rules.'}

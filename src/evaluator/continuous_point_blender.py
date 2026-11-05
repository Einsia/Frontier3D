"""Measure declared world-space query points against complete triangle surfaces."""
from pathlib import Path
import sys
import json
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from continuous_native_blender import TriangleQuery,join_mesh,read_bound,digest


if __name__=='__main__':
    path=Path(sys.argv[sys.argv.index('--')+1]);request=json.loads(path.read_text())
    query_path=read_bound(request['query_points'])
    with np.load(query_path,allow_pickle=False) as payload:points=payload['points_m'].copy()
    if points.ndim!=2 or points.shape[1]!=3 or not len(points) or not np.isfinite(points).all():
        raise ValueError('Complete finite world-space point population required')
    v,f=join_mesh(request['surface'])
    if not len(f): result={'status':'absent','reason':'Candidate surface absent'}
    else:
        distances,hits=TriangleQuery(v,f).nearest(points)
        result={'status':'measured','distances_m':distances.tolist(),'closest_world_m':hits.tolist()}
    result.update(request_sha256=digest(path),implementation=request['implementation'],
        query_points=request['query_points'],surface=request['surface'],registration='none',model_calls=0,
        candidate_code_executed=False)
    Path(request['output']).write_text(json.dumps(result,indent=2))

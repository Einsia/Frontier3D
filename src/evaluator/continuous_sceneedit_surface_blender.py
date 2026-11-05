"""Trusted full-triangle queries for the fixed L2 edit surface contract."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).resolve().parent))
from continuous_sceneedit_surface import compare
from continuous_native_blender import join_mesh,TriangleQuery,digest

if __name__=='__main__':
    path=Path(sys.argv[sys.argv.index('--')+1]);request=json.loads(path.read_text())
    surfaces={k:join_mesh(v) for k,v in request['surfaces'].items()}
    evidence=[p for items in request['surfaces'].values() for p in items]
    result=compare(surfaces,request['parameters'],TriangleQuery,evidence)
    output=Path(request['output']);output.mkdir(parents=True,exist_ok=True)
    (output/'result.json').write_text(json.dumps({'request_sha256':digest(path),'result':result},allow_nan=False)+'\n')

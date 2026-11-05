import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'codebase'
sys.path.insert(0,str(ROOT))
from tools import l3_leaderboard_batch
l3_leaderboard_batch.B=Path(os.environ['L3_EXPERIMENT_BATCH'])
from tools.l3_matrix_scoring import worker
worker(json.loads(Path(sys.argv[1]).read_text()))

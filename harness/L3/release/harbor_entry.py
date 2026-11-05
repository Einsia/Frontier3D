import os,sys
from pathlib import Path
import verify
args=[sys.argv[0],'--task',sys.argv[1]]
for option,key in [('trial','L3_TRIAL'),('engine','L3_ENGINE'),('model','L3_MODEL'),('effort','L3_EFFORT'),('provider','L3_JUDGE_PROVIDER')]:
 args += ['--'+option,os.environ[key]]
args+=['--output',os.environ.get('L3_VERIFY_OUTPUT','/logs/verifier/l3'),'--gpu',os.environ.get('L3_GPU','0')]
sys.argv=args
verify.main()

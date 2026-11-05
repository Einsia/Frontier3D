"""Text2Code 012 fixture authored solely from the public instruction; not model output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import blue, boolean, box, brass, cylinder, finish, ring, save, silver

base=box((.120,.120,.008),(0,0,.004))
for i,(x,y) in enumerate(((-.028,0),(.028,0),(0,-.028),(0,.028))):
    boolean(base,cylinder(.0042,.006,(x,y,.008)))
    finish(ring(.0125,.0042,.028,(x,y,.035),'Z'),f'Roller {i}',brass,(x*2.5,y*2.5,.055))
    finish(cylinder(.004,.046,(x,y,.029)),f'Pin {i}',silver,(x*4,y*4,.02))
    finish(ring(.007,.0042,.013,(x,y,.0145),'Z'),f'Spacer {i}',brass,(x*1.5,y*1.5,.030))
finish(base,'Base',blue,(0,0,-.025))
finish(box((.030,.030,.050),(0,0,.033)),'Workpiece',brass,(0,0,.110))

save()

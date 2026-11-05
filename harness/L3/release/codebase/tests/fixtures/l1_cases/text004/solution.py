"""Text2Code 004 fixture authored solely from the public instruction; not model output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import blue, boolean, box, cylinder, finish, ring, save, silver

finish(box((.160,.090,.010),(0,0,.005)), 'Base', blue, (0,0,-.030))
for i,x in enumerate((-.060,.020)):
    jaw=box((.018,.076,.050),(x,0,.035))
    for y,r in ((-.025,.0042),(0,.0052),(.025,.0042)):
        boolean(jaw,cylinder(r,.024,(x,y,.027),'X'))
    finish(jaw,f'Jaw {i}',blue,((-1 if i==0 else 1)*.075,0,.025))
for i,x in enumerate((-.0495,.0095)):
    finish(box((.003,.076,.020),(x,0,.050)),f'Liner {i}',blue,((-1 if i==0 else 1)*.030,0,.100))
for side in (-1,1):
    finish(cylinder(.004,.130,(0,side*.025,.027),'X'),f'Guide {side}',silver,(0,side*.100,.015))
finish(cylinder(.005,.150,(0,0,.027),'X'),'Drive rod',silver,(0,-.160,0))
hub=ring(.010,.0052,.012,(.081,0,.027),'X')
boolean(hub,cylinder(.0032,.026,(.081,0,.027),'Y'))
finish(hub,'Handle hub',blue,(.095,0,.020))
finish(cylinder(.003,.070,(.081,0,.027),'Y'),'Crossbar',silver,(.095,0,.090))

save()

"""Text2Code 006 fixture authored solely from the public instruction; not model output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    blue,
    boolean,
    box,
    brass,
    cylinder,
    fastening,
    finish,
    math,
    ring,
    save,
    silver,
)

base=box((.100,.100,.008),(0,0,.004))
boolean(base,cylinder(.0082,.012,(0,0,.004)))
for x in (-.040,.040):
    for y in (-.040,.040):
        boolean(base,cylinder(.0032,.012,(x,y,.004)))
        fastening(x,y,0,.0095,.008)
finish(base,'Base',blue,(0,0,-.030))
finish(ring(.014,.0082,.011,(0,0,.0135),'Z'),'Sleeve',brass,(0,.070,.030))
finish(cylinder(.008,.026,(0,0,.017)),'Spindle',silver,(-.09,0,.035))
disk=ring(.042,.0082,.008,(0,0,.023),'Z')
for i in range(6):
    a=i*math.pi/3
    boolean(disk,cylinder(.0032,.012,(.032*math.cos(a),.032*math.sin(a),.023)))
finish(disk,'Index disk',blue,(0,0,.095))
finish(cylinder(.003,.018,(.032,0,.022)),'Index pin',silver,(.085,0,.065))
finish(ring(.013,.0082,.003,(0,0,.030),'Z'),'Retaining ring',brass,(0,0,.145))

save()

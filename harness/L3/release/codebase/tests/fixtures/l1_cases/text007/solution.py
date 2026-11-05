"""Text2Code 007 fixture authored solely from the public instruction; not model output."""
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
    ring,
    save,
    silver,
)

plate=box((.150,.050,.005),(0,0,.0025))
for x in (-.068,.068):
    for y in (-.019,.019):
        boolean(plate,cylinder(.0032,.009,(x,y,.0025)))
        fastening(x,y,0,.0065,.005)
finish(plate,'Mounting plate',blue,(0,0,-.025))
for i,x in enumerate((-.045,.005,.055)):
    block=box((.014,.026,.025),(x,0,.0175))
    boolean(block,cylinder(.0052,.020,(x,0,.0205),'X'))
    finish(block,f'Guide block {i}',blue,((i-1)*.055,.060,.020))
finish(cylinder(.005,.118,(.005,0,.0205),'X'),'Sliding bolt',silver,(0,-.085,.025))
finish(cylinder(.003,.024,(-.015,0,.0375)),'Handle',silver,(0,0,.080))
finish(cylinder(.007,.010,(-.015,0,.0545)),'Grip',blue,(0,0,.115))
for i,x in enumerate((-.030,.025)):
    finish(ring(.008,.0052,.004,(x,0,.0205),'X'),f'Stop ring {i}',brass,((-1 if i==0 else 1)*.06,-.04,.04))

save()

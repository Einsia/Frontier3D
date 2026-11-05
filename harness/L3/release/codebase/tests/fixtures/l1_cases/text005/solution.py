"""Text2Code 005 fixture authored solely from the public instruction; not model output."""
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

OMIT_ONE_BASE_HOLE = False
BASE_HOLE_RADIUS = .0032
base=box((.080,.070,.008),(0,0,.004))
for x in (-.030,.030):
    for y in (-.024,.024):
        if not (OMIT_ONE_BASE_HOLE and x < 0 and y < 0):
            boolean(base,cylinder(BASE_HOLE_RADIUS,.012,(x,y,.004)))
        fastening(x,y,0,.0095,.008)
finish(base,'Base',blue,(0,0,-.030))
for side in (-1,1):
    x=side*.020
    cheek=box((.008,.042,.064),(x,0,.040))
    boolean(cheek,cylinder(.0052,.012,(x,0,.050),'X'))
    finish(cheek,f'Fork cheek {side}',blue,(side*.055,0,.025))
    finish(ring(.009,.0052,.003,(side*.028,0,.050),'X'),f'Collar {side}',brass,(side*.10,0,.035))
pulley=cylinder(.020,.01802,(0,0,.050),'X')
for x in (-.0105,.0105):
    boolean(pulley,cylinder(.025,.003,(x,0,.050),'X'),'UNION')
boolean(pulley,cylinder(.0082,.028,(0,0,.050),'X'))
finish(pulley,'Grooved pulley',blue,(0,0,.100))
finish(ring(.008,.0052,.024,(0,0,.050),'X'),'Bushing',brass,(0,.085,.070))
finish(cylinder(.005,.058,(0,0,.050),'X'),'Axle',silver,(0,-.105,.030))

save()

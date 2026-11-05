"""Text2Code 010 fixture authored solely from the public instruction; not model output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import blue, boolean, box, brass, cylinder, finish, ring, save, silver

outer=box((.044,.044,.080),(0,0,.040))
boolean(outer,box((.036,.036,.084),(0,0,.040)))
boolean(outer,cylinder(.0032,.052,(0,0,.066),'X'))
finish(outer,'Outer tube',blue,(0,0,0))
inner=box((.032,.032,.090),(0,0,.085))
boolean(inner,box((.026,.026,.094),(0,0,.085)))
boolean(inner,cylinder(.0032,.040,(0,0,.066),'X'))
finish(inner,'Inner tube',blue,(0,0,.100))
for i,z in enumerate((.008,.070)):
    guide=box((.0356,.0356,.008),(0,0,z))
    boolean(guide,box((.0324,.0324,.012),(0,0,z)))
    if i==1:
        boolean(guide,cylinder(.0032,.040,(0,0,.066),'X'))
    finish(guide,f'Guide ring {i}',brass,(.08,0,i*.075))
finish(box((.043,.043,.005),(0,0,-.0025)),'Bottom plug',blue,(0,0,-.070))
finish(box((.034,.034,.004),(0,0,.132)),'Top cap',blue,(0,0,.140))
finish(cylinder(.003,.058,(0,0,.066),'X'),'Locking pin',silver,(-.100,0,.030))
for side in (-1,1):
    finish(ring(.006,.0032,.002,(side*.030,0,.066),'X'),f'Pin retainer {side}',brass,(side*.090,-.060,0))

save()

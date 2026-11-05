"""Text2Code 009 fixture authored solely from the public instruction; not model output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import boolean, brass, cylinder, finish, material, ring, save, silver

housing=ring(.030,.026,.070,(0,0,.043),'Z')
for z in (.008,.078):
    # Extend cutter outside the opening; the internal recess depth is 2.1 mm.
    center=z+(.00005 if z==.008 else -.00005)
    boolean(housing,cylinder(.0297,.0041,(0,0,center)))
finish(housing,'Housing',brass,(0,0,0))
finish(ring(.021,.007,.062,(0,0,.043),'Z'),'Filter insert',material('Beige filter',(.65,.55,.32)),(.090,0,.090))
for i,z in enumerate((.004,.082)):
    side=-1 if i==0 else 1
    finish(ring(.034,.0052,.008,(0,0,z),'Z'),f'Cap {i}',brass,(0,0,side*.080))
for i,z in enumerate((.009,.077)):
    side=-1 if i==0 else 1
    finish(ring(.0295,.0263,.002,(0,0,z),'Z'),f'Seal {i}',material(f'Dark seal {i}',(.015,.015,.015)),(.075,0,side*.035))
finish(cylinder(.005,.090,(0,0,.043)),'Tie rod',silver,(-.09,0,.030))
finish(ring(.009,.0052,.005,(0,0,.090),'Z'),'Round nut',silver,(0,0,.135))
finish(ring(.011,.0052,.002,(0,0,-.003),'Z'),'Bottom washer',brass,(0,0,-.125))

save()

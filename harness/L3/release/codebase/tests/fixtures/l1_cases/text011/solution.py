"""Text2Code 011 fixture authored solely from the public instruction; not model output."""
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

base=box((.090,.090,.008),(0,0,.004))
boolean(base,cylinder(.0082,.012,(0,0,.004)))
for x in (-.035,.035):
    for y in (-.035,.035):
        boolean(base,cylinder(.0032,.012,(x,y,.004)))
        fastening(x,y,0,.0095,.008)
finish(base,'Base',blue,(0,0,-.030))
finish(ring(.018,.0082,.020,(0,0,.018),'Z'),'Pan sleeve',brass,(0,.090,0))
finish(cylinder(.008,.030,(0,0,.021)),'Spindle',silver,(-.10,0,.02))
fork=box((.064,.050,.006),(0,0,.031))
boolean(fork,cylinder(.0082,.010,(0,0,.031)))
finish(fork,'Fork base',blue,(0,0,.080))
for side in (-1,1):
    x=side*.028
    upright=box((.006,.050,.050),(x,0,.059))
    boolean(upright,cylinder(.0072,.010,(x,0,.069),'X'))
    finish(upright,f'Upright {side}',blue,(side*.065,0,.040))
    finish(ring(.007,.0042,.006,(x,0,.069),'X'),f'Tilt bushing {side}',brass,(side*.1,0,.080))
    finish(cylinder(.004,.016,(side*.024,0,.069),'X'),f'Tilt pin {side}',silver,(side*.11,0,.13))
platform=box((.048,.064,.010),(0,0,.069))
boolean(platform,cylinder(.0042,.054,(0,0,.069),'X'))
finish(platform,'Camera platform',blue,(0,0,.145))

save()

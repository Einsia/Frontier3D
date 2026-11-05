"""Text2Code 008 fixture authored solely from the public instruction; not model output."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    blue,
    boolean,
    box,
    cylinder,
    fastening,
    finish,
    material,
    ring,
    save,
    silver,
)

body=box((.100,.070,.035),(0,0,.0175))
boolean(body,box((.092,.062,.035),(0,0,.022)))
lid=box((.100,.070,.004),(0,0,.039))
for x in (-.040,.040):
    for y in (-.025,.025):
        boolean(body,cylinder(.0022,.010,(x,y,.0045)))
        boolean(lid,cylinder(.0022,.008,(x,y,.039)))
        finish(ring(.0045,.0022,.0325,(x,y,.02075),'Z'),f'Standoff {x} {y}',silver,(x*.7,y*.7,.035))
        fastening(x,y,.029,.0135,.041,shank_radius=.002,head_radius=.0036,washer_outer=.004,washer_inner=.0022)
finish(body,'Body',blue,(0,0,-.030))
finish(lid,'Lid',blue,(0,0,.130))
gasket=box((.100,.070,.002),(0,0,.036))
boolean(gasket,box((.092,.062,.006),(0,0,.036)))
finish(gasket,'Gasket',material('Dark gasket',(.015,.015,.015)),(0,0,.085))

save()

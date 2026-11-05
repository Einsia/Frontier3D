# Apartment elevator lobby: waiting delivery robot

Apartment elevator lobby: waiting delivery robot. Create a 3.6 x 2.4 m polished-stone lobby with a 600 mm floor grid and a 12-compartment mailbox bank, total width 1.80 m and bottom 0.30 m above floor. Fully open a 0.90 m elevator doorway. The car is 1.40 m deep and 1.60 m wide, with floor level difference at most 3 mm, aligned sill grooves within 2 mm, handrails on three walls at 0.90 m, a control panel and a mirror. The robot has a 0.50 x 0.45 m base, screen top at 1.20 m, three shelves and a 0.35 x 0.25 x 0.15 m parcel on the top tray with label upward. Face the door centreline within 5 degrees and keep its front edge 1.20 m from the sill. Mark a 1.50 m turning circle, clear except for the robot. Provide a continuous 0.80 m straight entry path with mailbox and fire-hose cabinet outside. The car must allow a conservative 0.75 m robot clearance envelope plus 0.30 m at each side. The top tray is 0.85 m high and the control panel 1.10 m; document an unobstructed reachable control position within 0.90 m of the panel after entry, while retaining the required waiting pose. Centre the parcel on the tray within 20 mm without overhang. Use 3000 K wall lamps and light spilling from the car. Frame robot, doorway and cabin depth; the alternate may look outward from inside. Static; no elevator or driving animation.

Use metres and Z up. Build editable, solid three-dimensional geometry with separable semantic components, meaningful thickness and plausible support. A static articulated robot pose is required; no controller, physical dynamics or manipulation trajectory is required. Represent specified joints and end-effectors geometrically. Reach spheres are geometric envelope checks, not certification of inverse-kinematic or dynamic feasibility. Keep specified frozen contacts distinct from other service targets; label service points in the scene/README without placing duplicate robots. Navigation clearance refers to the free route excluding the robot being evaluated; include all other furnishings and protrusions. Provide route sample coordinates and the measurement conventions in README. Do not use rendered photographs or billboards as substitutes for the complete scene.

Render main.png from the primary view described above. Render alternate.png from a second perspective camera chosen to expose the critical contacts and clearance routes; follow any suggested alternate view when useful. Both views must show the same geometry and frozen pose, at 1200 x 1000 pixels using Cycles, AgX, exposure 0 and gamma 1. Retain both cameras and pack textures. The README must map semantic object names to required objects, measurements and service points. Text-only input: no starting scene or external reference asset is supplied. The complete normalized brief above is normative; no evaluator-only constraint may be used as an additional requirement.

## Submission contract

```text
output/
  solution.py
  scene.blend
  main.png
  alternate.png
  README.md
  assets/  # optional bundled dependencies
```

`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`

The entry point must run from a clean workspace, read only the supplied input/ and bundled output/assets/ (bundled helper code and installed libraries are allowed), and recreate the scene and all required renders. Resolve dependencies relative to the script, without personal absolute paths or earlier submissions. Document execution and dependencies in README.md. All images must come from the same scene and specified cameras; retain cameras and pack textures.

# Coffee station: midway through latte art

Coffee station: midway through latte art. Create a close elevated view of a 1.80 m counter, 0.95 m high and 0.60 m deep, in pale wood. From left to right place a single-group espresso machine, 0.55 m wide and 0.45 m high, with a portafilter locked beneath the group and pressure needle mid-scale; a grinder with transparent hopper and beans; a tamper and dosing-cup holder. Rear shelving holds three coffee bags and a cup rack. A rear-centre arm has base height 1.00 m and reach 0.85 m, gripping a 0.35-litre stainless milk pitcher. Its spout is 0.03 m above a 250 ml latte cup, pitcher tilted 20 +/-2 degrees, spout extension aimed toward the rear third of the liquid surface. Show a static leaf-pattern milk-foam base using local texture or shallow relief; cup handle points right 45 degrees. Four cups line the front at 0.15 m spacing, one inverted on a draining rack. Keep a 0.80 m rear working depth and at least 0.15 m between the arm sweep and shelf underside. The brewing head, grinder outlet and two representative cup-row endpoints must be within 0.80 m of the arm base at heights 0.90-1.40 m. Tilt the pitcher opposite the cup-handle direction and keep its lowest point at least 0.05 m clear of shelves and other cups. Use warm wood, black equipment, brass details and ivory cups with warm side-window light and counter spots. Frame pitcher, latte surface and brewing head in a shallow-depth-of-field close view. Static; no milk stream, steam jet or cup movement.

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

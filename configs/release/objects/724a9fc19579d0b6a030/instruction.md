# Greenhouse: tomato-picking robot

Greenhouse: tomato-picking robot. Create a 12 x 5 m greenhouse with arch frames every 2 m, a cover transmitting about 40% light and reflective ground fabric. Two parallel planting troughs are 0.55 m high and 0.40 m wide. Keep a 1.50 m clear inter-row corridor, continuously traversable, and at least 0.45 m clear on designated walking routes. Vines climb taut individual strings to 2.20 m. Build volumetric clusters of low-poly leaves, not one crossed billboard. One bunch has six tomatoes of 0.05-0.07 m diameter, a cluster axis tilted downward 20 degrees and stems joining a main stalk. The robot has 0.60 m wide tracks, 0.90 m ground-contact length and a six-axis arm of 0.90 m reach. Its suction cup touches the second fruit, contact-ring penetration at most 3 mm and axis through the fruit centre. Electric shear blades open 15 degrees, sit 0.02 m behind the stem and straddle its cross-section. A front harvest basket has a 0.40 x 0.30 m opening at 0.40 m height and contains three fruits. Keep each track edge at least 0.20 m from the troughs and exclude hanging vines from the route. Target fruit, cluster-top fruit and nearby corridor centre must be within 0.85 m of the arm base; target height is 0.80-1.60 m. Maintain simultaneous suction contact and cutting alignment, with at least 10 mm gap to neighbouring fruit. Use green foliage, red fruit, ivory troughs and a silver-grey robot with morning grid shadows. Frame arm, fruit bunch and corridor; an alternate view may look along the row. Static; no detachment, juice or vine-growth animation.

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

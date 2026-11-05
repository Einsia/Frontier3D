# Drone dock: battery swap in progress

Drone dock: battery swap in progress. Create an outdoor dock about 2.2 x 2.2 m, seen close from above at an oblique angle. Use a two-tier box base with a circular 1.60 m landing pad, H marking, inner graduations, two symmetric limit blocks, three positioning cones and a fourth auxiliary cone. Open both housing doors 80 +/-3 degrees, showing wiring and guides, with a half-lit side status strip. A quadrotor of 0.60 m motor spacing and 0.45 m body length rests level within 2 degrees, its four feet seated in the cone positions with at most 5 mm gaps. Propellers are stationary at different natural orientations. Slide the rear battery hatch 70% open. A swapping arm from a rear column holds a charged 0.20 x 0.12 x 0.06 m battery, inserted 60 +/-5% along the tail-bay rails. Align guide features within 2 mm and maintain gripper contact with at most 2 mm penetration. The removed depleted battery rests at a turntable waiting position inside the dock, visually matching the charged one except for a red charge label; it must not occupy the same bay. Add a 0.40 m anemometer mast and a beacon at the pad edge. Keep door sweep volumes free and a continuous 0.30 m maintenance band around the dock. Swap point, waiting turntable and an above-propeller inspection point must lie inside the arm working sphere at heights 0.80-1.30 m. Insertion direction is parallel to the fuselage axis within 2 degrees and the batteries remain geometrically exclusive. Use white-grey aircraft, orange blade tips, dark-grey dock and pale ground with low warm morning light and long pad shadows. Frame aircraft, partially inserted battery and open doors; the alternate may be an overhead view of pad markings and restraints. Static; no rotor rotation, flight or battery-motion animation.

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

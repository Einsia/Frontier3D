# Library: high-shelf book retrieval

Library: high-shelf book retrieval. Create a 4.8 x 1.2 m library section, seen obliquely from a low angle. A one-sided steel shelf is 4.80 m long and 0.30 m deep, with six levels at 0.30, 0.68, 1.06, 1.44, 1.82 and 2.20 m, within 10 mm. Fill shelves with restrained-colour books of 0.24-0.32 m height. On the top level show a 0.03 m spine gap associated with the target book. Centre a lifting-column robot in front, with 0.55 x 0.50 m bumper-equipped base, column top at 2.05 m and a horizontal end arm. Its two-finger gripper grips the target spine and extracts the book 40 +/-5 mm beyond the shelf front while preserving its upright orientation within 2 degrees of neighbouring books. A front receiving tray opens upward, its opening centre aligned beneath the book centre within 5 mm and separated vertically by 1.10 m. Keep the aisle 0.85 +/-0.03 m clear, checked every 0.25 m; ordinary books protrude at most 5 mm. Connect both aisle ends into a loop and keep at least 0.15 m base-to-shelf clearance. Use a 0.15-2.05 m lift stroke and a fixed 0.15 m upward tool-reference offset to reach both the 2.20 m top target and 0.30 m bottom return position. Pickup/return reference heights refer to the book bottom. Gripper contact penetration is at most 2 mm and the extracted book has 2 mm clearance from both neighbours. Use warm shelf lights, beige spines and dark-grey robot. Frame the lift column, partially extracted book and empty position. Static; no page turning or lift animation.

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

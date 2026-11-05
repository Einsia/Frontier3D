# Tool room: retrieving from a pegboard

Tool room: retrieving from a pegboard. Create a 3.0 x 2.4 m tool room with perforated wall panels, viewed above one side of the workbench. The steel-topped bench is 1.50 x 0.70 m at 0.90 m height with layout marks. A left-end vise grips a flange 0.12 m in diameter and 0.03 m thick without intersection. A 1.20 x 0.80 m pegboard starts 0.10 m above the bench. Outline five wrenches, four screwdrivers and two pliers; the double-ended ring wrench is removed, leaving its complete matching outline. A fixed arm at the rear-centre has base height 0.95 m and reach 0.85 m. Its two-finger gripper holds the wrench at mid-handle 0.30 m above the worktop, working ring end aimed toward the flange within 5 degrees, contact penetration at most 2 mm. Add three bolts, a rag and a parts tray. Keep at least 0.80 m operating depth in front and a continuous 0.90 m side passage. All eleven tool pickup positions, including the empty wrench position, must be within 0.85 m of the arm base and in the 0.95-1.75 m height band. The empty outline exactly matches the held wrench, and remaining tools do not overlap neighbouring positions. Use grey-white wall panels, orange tool outlines, a dark-grey arm and cool-white light. Frame arm, wrench and empty outline; an alternate may look back from the vise. Static; no tool-use or assembly animation.

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

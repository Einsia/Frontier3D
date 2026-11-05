# Humanoid test track: midway through obstacles

Humanoid test track: midway through obstacles. Create a 10 x 4 m test area with blue sports flooring and white boundary lines. The marked course is 1.20 +/-0.02 m wide, except the explicitly narrower handrail passage. In sequence, add a 15-degree ramp 1.50 m long and 1.20 m wide with anti-slip stripes; three steps each 0.15 +/-0.005 m high and 0.30 m deep; a 0.45 m wide, 0.30 m deep gap with bevelled yellow edges; five posts 0.08 m in diameter and 0.50 m high, alternately offset laterally by 0.40 m and spaced 0.80 m longitudinally; then a 2.00 m handrail corridor of 0.90 m clear width, rails at 0.90 m, diameter 0.04 m, posts no more than 0.80 m apart. Freeze a humanoid, 1.30 m tall and 0.40 m shoulder width, on the first step: front sole on the tread with at most 30 mm toe overhang, rear foot on the ramp, knee bent about 60 degrees and torso leaning 8 +/-2 degrees. Swing arms oppositely and point head camera toward the next step. Add three 1.80 m fill-light posts, a tripod camera and start/end signs outside the route. Exclude undesigned obstacles from the marked lane and leave 0.30 m safety margins beside the ramp. Step fronts and posts are within 0.60 m of the course centreline. Foot penetration into support surfaces is at most 3 mm; use the torso vertical projection as a declared geometric balance proxy, within the front-foot support region allowing 0.05 m tolerance, not a dynamic stability claim. Use grey-black body, orange joints, plain barriers and even high-bay/fill lighting. Frame ramp, stepping robot and subsequent course depth. Static; no gait simulation, falls or sensor visualization.

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

# Parking garage: charging robot before insertion

Parking garage: charging robot before insertion. Create a 2.50 x 5.30 m parking bay with dark-grey epoxy, 0.12 m white bay lines, a bay number and directional arrows. One side has a protected pillar with charging sign; a dark car occupies the neighbouring bay, leaving 0.70 m between cars. The target silver-grey car is 1.85 m wide and 4.80 m long, doors closed and left-rear charging flap open 60 degrees. Beside it place a 0.60 x 0.50 m four-wheel robot with a front wheel on a guide marking, 1.10 m column and two-joint top arm holding a national-standard DC connector 0.25 m long on a 0.03 m cable. Freeze just before insertion: connector tip is 0.02 m from the port plane, axes aligned within 3 degrees and latch upward. The cable hangs in a slack catenary from a sliding overhead suspension about 2.40 m high to the gripper, never taut, with at least 0.05 m clearance from the car. Add a rear-wall distribution box, emergency stop and blue standby light. Keep a 2.40 m front driving aisle and a continuous 0.60 m escape passage on the side opposite the robot. Port centre is at 0.90 m, inside the 0.60-1.20 m working-height band and within 0.80 m horizontal distance of the arm base. The open flap stays at least 0.03 m from the connector envelope and connector guide surfaces align with port grooves. Use reflective flooring, cool-white ceiling strips and a red connector accent. Frame robot, arm and port relationship. Static; no vehicle motion, plugging animation or electrical effects.

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

# Bar: dual-arm cocktail robot

Bar: dual-arm cocktail robot. Create a 2.40 m bar counter at 1.05 m height, within 10 mm, and 0.45 m depth, seen obliquely from the customer side. Use dark stone with a washing well and ice well, each 0.35 m wide and 0.05 m below the surface. Place four stools at 0.75 m seat height. An overhead storage rack, underside 0.35 m above the counter, carries eight inverted bottles with at least 80 mm between them, one removed. The robot has a 1.20 m torso and two arms of 0.75 m reach, bases at 0.95 m and 0.35 m apart. Freeze the moment before mixing: the right gripper holds a 0.22 m tall, 0.08 m diameter metal shaker with mouth 0.03 m above a whisky-glass rim, tilted toward it 15 +/-2 degrees. Put one ice sphere in the glass. The left gripper holds the removed bottle at its middle, mouth downward and stopper toward the shaker, with at most 2 mm penetration. Arrange four glasses at 0.12 m spacing, handles where applicable facing right 45 degrees. Keep a 0.80 m rear operating aisle and at least 0.15 m between arm sweep and storage underside. Bottle pickup, washing well, ice well and target glass must each lie within a 0.70 m working sphere of at least one arm. The shaker-axis extension crosses the glass opening centre within 10 mm; the empty bottle hook matches the removed bottle's orientation. Use dark-green tile, brass pendants, warm wood, stainless tools, amber drink colour, 2800 K light and bottle-rack spots. Frame arms, shaker, glasses and bottles. Static; no liquid flow, ice physics or people.

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

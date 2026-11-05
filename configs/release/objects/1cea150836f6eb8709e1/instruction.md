# Laundry: dual-arm folding workstation

Laundry: dual-arm folding workstation. Create a roughly 4.2 x 3.6 m laundry room with pale-grey tiles and three front-loading washers along a wall, each 0.60 x 0.60 m and 0.85 m tall. Open the middle door 130 degrees, exposing its drum and two waiting textiles; put a basket on each machine. Opposite storage has four compartments with four differently coloured detergent bottles and towel stacks. A central non-slip folding table is 1.60 x 0.80 m at 0.90 m. Two arms on a rear frame have bases at 1.15 m, 0.30 m apart, and 0.70 m reach each. Freeze flattening: their grippers hold opposite corners of a 0.70 x 1.40 m towel, stretched 0.15 m above the table. Its plane is nearly horizontal with at most 0.05 m corner-height variation; its centreline matches the table's long axis within 20 mm. Gripper penetration is at most 2 mm; hanging edges form natural curves, not rigid straight edges. Put two baskets beneath the table and three folded stacks beside it. Provide a continuous 0.90 m loop around the table and at least 0.70 m clear in front of the washers. Each current towel grasp must be within its corresponding fixed arm's 0.70 m reach. Drum opening, towel compartment and table service heights are 0.40-1.20 m for human transfer; the fixed arms need not reach across the 0.90 m aisle to the washers or storage. Each held corner corresponds to one gripper without crossed hands; keep at least 0.10 m between arms and the washer door's swept volume. Use white tile wainscot, light timber storage and coloured baskets, cool-white light plus a warm drum accent. Frame arms, suspended towel and open washer. Static; no cloth solver, water or drum rotation.

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

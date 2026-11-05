# Spring hinges - Engsel pegas rak piring

Use input/reference.png, input/front.png, input/side.png and input/top.png. They show the same object and pose.

Reconstruct the wall cabinet with its upward-opening framed door, two top hinges, and the two articulated telescoping support struts. Retain the cabinet cavity, thin panels, door frame and translucent infill. The door must rotate about its upper hinge axis; each strut must pivot at its cabinet and door attachments and slide along its own axis while remaining attached. Do not fake opening by translating the entire door or stretching rigid parts. No pressure or spring-force simulation is required.

Use real editable three-dimensional geometry. Preserve continuous curvature, thickness, recesses, openings, thin structures, connections and occlusions. Distinct components should be editable objects or clearly separable mesh islands; organic surfaces may remain continuous. Exact source topology, vertex count and object names are not required. Image planes or camera-facing shells are not substitutes for full geometry.

Use metres, Z up, and a maximum overall span of 1.000 m with 2% tolerance, excluding cameras and lights. This is a task scale convention, not a real-world measurement. Infer other proportions from the images.

The four main views show the open pose. input/closed.png and input/half_open.png use the same primary camera to show the closed and intermediate poses. Follow input/motion.json at 24 fps: frame 1 closed, 31 half open, 61 open, 91 half closed and 121 closed again. Animate continuously through the cycle; match the visible poses, attachment relationships and rotation direction rather than the exact source easing. Measure the 1 m span at frame 1. Keep rigid component shape and scale constant. Save the Blender scene at frame 61 for inspection; preserve the full 1–121 animation in Blender and GLB. Render main.png at frame 61. An exploded view is not required.

Render main.png at 1000 x 1000 pixels from a camera matching input/reference.png, using neutral studio lighting, Cycles, AgX and exposure 0. Retain the camera and lighting in scene.blend.

## Submission contract
Place all deliverables under `output/`:

```text
output/
  solution.py
  scene.blend
  scene.glb
  main.png
  README.md
  assets/       # optional self-contained helpers and textures
```

Rebuild from a clean workspace using:
`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`

The entry point must generate or refresh all required scene and image files without depending on previously generated outputs. Resolve helpers relative to the script. Read only the supplied input files, your own bundled helper code/assets and installed libraries. Do not download the source model, its textures or additional reference views, or embed externally retrieved source geometry in your script. Do not read evaluator-private files or use personal absolute paths. Pack textures into the Blender file or use portable paths within output/assets/. Record execution and dependencies in output/README.md. Optional logs and renders belong in output/logs/ and output/renders/.

## Materials

Use solid colors or procedural materials only. Reference images are for observation. Do not use bitmap textures, HDRIs, baked/generated images, or image-driven shaders, lights, geometry nodes or compositing. Procedural Noise and Bump nodes are allowed.

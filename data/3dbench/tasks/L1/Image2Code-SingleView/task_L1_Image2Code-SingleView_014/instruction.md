# Birkin Caballo

Use only input/reference.png to reconstruct a complete three-dimensional object. Match visible surfaces; complete unseen surfaces plausibly without inventing internal machinery. No additional view or initial mesh is supplied.

Reconstruct the handbag and the visible attached ornaments shown in the input. Preserve the soft trapezoidal body, two arched handles, folded flap, straps, central closure hardware, edge seams and any hanging charm that is visible. Match the leather colour, soft panel curvature, folds and metal accents. Do not add detached background accessories; microscopic stitching and exact logos may be simplified.

Use real editable three-dimensional geometry. Preserve continuous curvature, thickness, recesses, openings, thin structures, connections and occlusions. Distinct components should be editable objects or clearly separable mesh islands; organic surfaces may remain continuous. Exact source topology, vertex count and object names are not required. Image planes or camera-facing shells are not substitutes for full geometry.

Use metres, Z up, and a maximum overall span of 1.000 m with 2% tolerance, excluding cameras and lights. This is a task scale convention, not a real-world measurement. Infer other proportions from the images.

Save the final static pose at frame 1 and export the same pose to scene.glb. Animation, exploded views and simulation are not required.

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

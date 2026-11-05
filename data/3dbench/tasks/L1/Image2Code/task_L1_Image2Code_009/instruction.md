# Spherical floating robot

Reconstruct the object using input/reference.png together with input/front.png, input/side.png and input/top.png. All four images show the same object and static pose.

Reconstruct the floating robot in the displayed static pose. Preserve the layered spherical body, separated shell bands, circular side housings and recessed mechanical areas, the front optical opening, the jointed side arms, and the curved claw panels. Follow the actual gaps, overlaps, taper and panel thickness visible in the images. All arms and panels must have plausible attachments to the body even though the robot has no ground support. Use the plain olive-green material shown in these references; labels, hazard stripes and weathering are not required. Do not add legs or a pedestal.

Use Blender to create real, editable surfaces. Match the silhouette, continuous curvature, major recesses and protrusions, thickness, spacing and occlusion. Organic surfaces may be one continuous mesh; genuinely distinct components should be editable objects or clearly separable mesh islands. Exact source topology, vertex count, object names and microscopic texture details are not required. Do not use image planes or camera-facing shells as substitutes for full geometry.

Use 1.000 m as the maximum overall span of the object (excluding lights and cameras), with a 2% tolerance. This is a task scale convention, not a real-world measurement. Infer other proportions from the images. Use metres and Z up. Save the final static pose at frame 1; animation, an exploded view and simulation are not required. Export the same pose to scene.glb. Render main.png at 1000 x 1000 from a camera matching reference.png, with neutral studio lighting, Cycles, AgX and exposure 0. Retain the camera and lighting in scene.blend.

## Submission contract
Place every deliverable under `output/` in the task workspace. The evaluator reads these exact paths:

```text
output/
  solution.py       # reproducible Blender generation entry point
  scene.blend       # editable native scene, final static pose at frame 1
  scene.glb         # geometry and materials in the same static pose
  main.png          # 1000 x 1000 primary-view render
  README.md         # execution, dependencies and material notes
  assets/           # optional local helper code and procedural textures
```

Run from a clean workspace:
`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`

The entry point must generate or refresh scene.blend, scene.glb and main.png without relying on previously generated outputs. Resolve helpers relative to the script and use only the supplied input files, your bundled assets/code and installed libraries. Do not fetch the source mesh, textures or additional source views from the internet, and do not encode an externally retrieved source mesh inside the script. Do not use hard-coded personal paths. Pack dependencies into the Blender file or use portable relative paths under output/assets/. Optional renders and logs belong under output/renders/ and output/logs/.

## Materials

Use solid colors or procedural materials only. Reference images are for observation. Do not use bitmap textures, HDRIs, baked/generated images, or image-driven shaders, lights, geometry nodes or compositing. Procedural Noise and Bump nodes are allowed.

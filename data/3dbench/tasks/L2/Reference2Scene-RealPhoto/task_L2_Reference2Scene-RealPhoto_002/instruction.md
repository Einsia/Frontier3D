Reconstruct the white kitchen counter, inset dark sink and the visible edge of the black cooktop. Arrange the dark blue deep plate, wooden spoon, round wooden board, upright purple mug, white dish, white mug lying on its side, light blue tilted mug and dark blue mug lying on its side as shown. Match their relative size, orientation, spacing, overlaps and contact with the counter or board. Model the hollow interiors, rims, bases and visible handles of the vessels, the depth of the sink and the thickness of the counter and board. Preserve the white, blue, purple and wood material contrast, ceramic highlights and overhead oblique composition. Small logos and distant background furniture may be simplified.

Inputs: input/reference.png. Use metres and Z up. Keep major components independently editable, with thickness, support and meaningful spacing. Do not substitute the complete reference on a plane or a single-camera projection for three-dimensional geometry. Local material textures are allowed.

No original 3D model, depth map or calibrated camera is supplied. Use a dark blue plate diameter of 0.26 m as the task scale convention, not a measured real-world dimension. Infer other dimensions proportionally and complete hidden surfaces plausibly.

Create a perspective camera matching the input and render main.png. Copy it and translate 0.30 m to its right along local X without changing rotation or lens; render alternate.png and retain both cameras. This second view checks real three-dimensional structure; unseen real-world details need not be uniquely recovered.

Render every required image from the same scene using Cycles at 960 × 720 pixels, AgX and exposure 0. Use only the supplied inputs to establish this scene; do not retrieve its original source model or additional source views.

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

## Materials

Local textures and packed dependencies are allowed. Build actual three-dimensional geometry; do not replace the scene with a complete-reference image plane or camera projection.

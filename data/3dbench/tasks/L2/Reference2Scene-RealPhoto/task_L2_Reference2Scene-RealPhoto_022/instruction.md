Reconstruct the stepped outdoor shopping plaza, white tensile canopy with posts/cables, glass-fronted building and sunset skyline. Preserve plaza levels, canopy curvature, circulation space and warm/cool light contrast. Distant skyline and small storefront signs may be simplified; canopy supports and level changes require geometry.

Inputs: input/reference.png. Use metres and Z up. Keep major components independently editable, with thickness, support and meaningful spacing. Do not substitute the complete reference on a plane or a single-camera projection for three-dimensional geometry. Local material textures are allowed.

No original 3D model, depth map or calibrated camera is supplied. Use a 1.1 m public-terrace railing height as the task scale convention, not a measured real-world dimension. Infer other dimensions proportionally and complete hidden surfaces plausibly.

Create a perspective camera matching the input and render main.png. Copy it and translate 0.30 m to its right along local X without changing rotation or lens; render alternate.png and retain both cameras. This second view checks real three-dimensional structure; unseen real-world details need not be uniquely recovered.

Render every required image from the same scene using Cycles at 1600 × 1200 pixels, AgX and exposure 0. Use only the supplied inputs to establish this scene; do not retrieve its original source model or additional source views.

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

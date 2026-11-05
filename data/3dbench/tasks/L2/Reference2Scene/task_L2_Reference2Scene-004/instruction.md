Reconstruct the country kitchen's run of pale cabinets, black cooker and hood, wooden worktops, foreground preparation island and window-side table and chairs. Include the kettle, cookware, open book, cutting board, vegetables and hanging pendant as recognizable grouped props. Preserve cabinet divisions, counter thickness, window geometry and walking gaps; fine food and text details can be simplified.

Inputs: input/reference.png. Use metres and Z up. Keep major components independently editable, with thickness, support and meaningful spacing. Do not substitute the complete reference on a plane or a single-camera projection for three-dimensional geometry. Local material textures are allowed.

Infer relative dimensions and perspective from the image, using a plausible metric scale. Absolute source coordinates are not a target because calibrated dimensions are not supplied.

Create a perspective camera matching the input and render main.png. Copy it and translate 0.30 m to its right along local X without changing rotation or lens; render alternate.png and retain both cameras. This second view checks real three-dimensional structure; unseen real-world details need not be uniquely recovered.

Render every required image from the same scene using Cycles at 1600 × 900 pixels, AgX and exposure 0. Use only the supplied inputs to establish this scene; do not retrieve its original source model or additional source views.

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

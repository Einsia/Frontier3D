Reconstruct the dark rectangular table and its crowded arrangement of household objects: the blue colander, turquoise watering can, white dish rack with cups and a green brush, stacked food containers, frying pan, cutting boards, mugs, plant, cork trivet, knives, spatula and cleaning brushes. Include the blue mats, visible chairs and the ironing board behind the table. Preserve the relative positions, colors, object orientations, overlaps and contact with the supporting surfaces. Cups, colander, pan and rack need real walls and openings; handles and long tools need three-dimensional volume. Fine foliage, brush bristles, small packaging text and background details may be simplified while retaining their overall appearance.

Inputs: input/reference.png. Use metres and Z up. Keep major components independently editable, with thickness, support and meaningful spacing. Do not substitute the complete reference on a plane or a single-camera projection for three-dimensional geometry. Local material textures are allowed.

No original 3D model, depth map or calibrated camera is supplied. Use a table-top width of 1.20 m as the task scale convention, not a measured real-world dimension. Infer other dimensions proportionally and complete hidden surfaces plausibly.

Create a perspective camera matching the input and render main.png. Copy it and translate 0.30 m to its right along local X without changing rotation or lens; render alternate.png and retain both cameras. This second view checks real three-dimensional structure; unseen real-world details need not be uniquely recovered.

Render every required image from the same scene using Cycles at 1439 × 1079 pixels, AgX and exposure 0. Use only the supplied inputs to establish this scene; do not retrieve its original source model or additional source views.

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

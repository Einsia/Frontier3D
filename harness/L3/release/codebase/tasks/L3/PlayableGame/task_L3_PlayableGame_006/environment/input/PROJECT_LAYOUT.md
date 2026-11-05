# Submission layout

output/
  README.md
  ue5_project/
    3DBenchGame.uproject
    Config/
    Content/
    SourceAssets/Blender/
    Source/   (if used)
    Plugins/  (if used)

Only instruction.md and environment/ are exposed to the model. environment/ is mounted into the workspace preserving input/ paths. The reference.png image is supplied as an actual visual input or is accessible through an image-viewing tool. solution/ remains private. No generated build/cache folders are required.

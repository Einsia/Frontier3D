Integration candidate authored from Text2Code 001's public dimensions only.
It is not a model result and does not read private reference assets.
Requires Blender 5.2.1 with the bundled glTF exporter; no external libraries.

Run from a clean task workspace:
blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

The script saves scene.blend and frame-1 scene.glb. It includes frame-61
exploded part transforms and retains the frame-1 keyframes.

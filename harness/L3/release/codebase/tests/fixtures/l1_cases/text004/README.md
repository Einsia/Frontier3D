Public-instruction integration candidate for Text2Code 004; not a model answer or private GT.
Requires Blender 5.2.1. Keep common.py beside solution.py; it contains portable
Blender helpers and uses only the supplied input/output arguments.

blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

The script builds independent solids, saves the assembled scene with a frame-61
explosion, and directly exports the assembled GLB. No old output is loaded.

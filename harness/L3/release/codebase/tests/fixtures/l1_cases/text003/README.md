Public-instruction candidate for Text2Code 003; not a model answer or private GT.
Requires Blender 5.2.1. Keep common.py beside solution.py; it contains local
Blender construction helpers and reads only the supplied command arguments.

blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

The script saves the assembled scene, frame-61 part transforms and assembled GLB.

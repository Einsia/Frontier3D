Public-instruction coupling fixture for Text2Code 015; not model output or GT.
Requires Blender 5.2.1. Keep common.py beside solution.py. Coordinates choose a
legal origin at the lower flange mid-plane; the two shafts remain separate.

blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

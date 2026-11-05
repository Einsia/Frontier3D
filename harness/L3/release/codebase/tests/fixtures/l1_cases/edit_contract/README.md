Public-input CodeEdit fixture, not a model answer or private target.
Default: reopen the supplied initial Blender scene and export without edits.
This is deliberately a negative example; unchanged targets must be detected.
The enlarge_washer variant performs CodeEdit 015's real Boolean radius-12 mm cut
in the public input, preserving other geometry/materials and world coordinates.

Blender 5.2.1; no CAD installation or internet dependency:
blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

All outputs are refreshed from the public input and local variant configuration.

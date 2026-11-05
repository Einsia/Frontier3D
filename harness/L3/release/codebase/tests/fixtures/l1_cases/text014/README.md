Public-instruction integration fixture, not a model answer or private GT.
The bundled mesh was authored using the five public interpolation points,
GeomAPI_Interpolate and corrected-Frenet rectangular sweep. No source model was
downloaded. See assets/provenance.json for package, builder and asset hashes.

Runtime: Blender 5.2.1 and the bundled assets/ directory; no CAD installation is
required inside the candidate container. The entry reconstructs editable geometry
from our own asset, saves the native scene and directly exports GLB at frame 1.

blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

Optional fixture re-authoring: run build_public_mesh.py with
cadquery-ocp-novtk==7.9.3.1.1; this is not required by solution.py. This candidate
validates the runtime/scoring contract, not the evaluator's still-missing exact
curve/surface tolerances or material semantics.

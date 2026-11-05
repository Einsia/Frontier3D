Controlled countermodel for the image-case delivery and scale contract.
It intentionally renders a blue box, not the depicted object. It is not a model
answer, does not access GT, and must never yield full semantic acceptance.
The optional assets/case.json varies scale, effective pixel size and exposure
for actual geometry/rendering boundary checks. No reference image is copied.

Run with Blender 5.2.1:
blender --background --factory-startup --python output/solution.py -- --input-dir input --output-dir output

Cycles renders main.png, and camera/lighting/settings are saved in scene.blend.
GLB and all images are built afresh. No internet, personal path, or old output
dependency. This box has no explosion; it cannot satisfy assembly semantics.
